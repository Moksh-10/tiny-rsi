// game-agent is a bounded, guest-only Ollama actor. Model output is data, never a command.
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"runtime"
	"strings"
	"syscall"
	"time"
)

var revision = "development"

const baseURL = "http://127.0.0.1:11434"
const maxResponse = 1 << 20

type object = map[string]any
type environment struct {
	cmd *exec.Cmd
	in  io.WriteCloser
	out *bufio.Scanner
}

func startEnvironment(ctx context.Context, path string) (*environment, error) {
	cmd := exec.CommandContext(ctx, path) // Trusted operator-supplied path; no shell or model arguments.
	cmd.Stderr = os.Stderr
	in, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	out, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	if err = cmd.Start(); err != nil {
		return nil, err
	}
	scan := bufio.NewScanner(out)
	scan.Buffer(make([]byte, 8192), maxResponse)
	return &environment{cmd, in, scan}, nil
}
func (e *environment) call(q object) (object, error) {
	if err := json.NewEncoder(e.in).Encode(q); err != nil {
		return nil, err
	}
	if !e.out.Scan() {
		return nil, fmt.Errorf("environment closed: %v", e.out.Err())
	}
	var r object
	if err := json.Unmarshal(e.out.Bytes(), &r); err != nil {
		return nil, err
	}
	return r, nil
}
func guestCheck() error {
	if runtime.GOOS != "linux" {
		return errors.New("rollouts require the provisioned Linux VM; use agent/scripts/worker.sh")
	}
	sealed, sealErr := os.ReadFile("/run/game-research/sealed")
	if sealErr != nil || string(sealed) != "sealed-v1\n" {
		return errors.New("worker must be sealed before rollouts")
	}
	sealStat, sealErr := os.Stat("/run/game-research/sealed")
	if sealErr != nil {
		return sealErr
	}
	owner, valid := sealStat.Sys().(*syscall.Stat_t)
	if !valid || owner.Uid != 0 || sealStat.Mode().Perm()&022 != 0 {
		return errors.New("invalid seal ownership")
	}
	b, err := os.ReadFile("/etc/game-research/worker")
	if err != nil || string(b) != "game-research-lima-v1\n" {
		return errors.New("missing provisioned worker marker")
	}
	st, err := os.Stat("/etc/game-research/worker")
	if err != nil {
		return err
	}
	stat, ok := st.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != 0 || st.Mode().Perm()&022 != 0 || os.Geteuid() == 0 {
		return errors.New("worker marker must be root-owned and actor must be unprivileged")
	}
	b, err = exec.Command("systemd-detect-virt", "--vm").Output()
	if err != nil || strings.TrimSpace(string(b)) == "none" {
		return errors.New("VM virtualization not detected")
	}
	b, err = os.ReadFile("/proc/mounts")
	if err != nil {
		return err
	}
	for _, line := range strings.Split(string(b), "\n") {
		f := strings.Fields(line)
		if len(f) > 2 && (f[2] == "virtiofs" || f[2] == "9p" || strings.Contains(f[2], "sshfs")) {
			return errors.New("host-sharing filesystem detected")
		}
	}
	return nil
}
func api(ctx context.Context, client *http.Client, path string, body any, result any) error {
	var reader io.Reader
	method := "GET"
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(b)
		method = "POST"
	}
	req, err := http.NewRequestWithContext(ctx, method, baseURL+path, reader)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(io.LimitReader(resp.Body, maxResponse+1))
	if err != nil {
		return err
	}
	if len(b) > maxResponse {
		return errors.New("Ollama response exceeds limit")
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("Ollama HTTP %d: %.512s", resp.StatusCode, b)
	}
	return json.Unmarshal(b, result)
}
func schema(game string) object {
	num := func(lo, hi float64) object { return object{"type": "number", "minimum": lo, "maximum": hi} }
	props := object{"type": object{"type": "string", "enum": []string{"launch", "wait", "ability"}}, "ticks": object{"type": "integer", "minimum": 1, "maximum": 120}, "x": num(-95, 95), "y": num(-95, 95)}
	required := []string{"type", "ticks"}
	if game == "getting-over-it" {
		props["type"] = object{"type": "string", "const": "hammer"}
		props["x"] = num(-3.15, 3.15)
		props["y"] = num(-3.15, 3.15)
		props["hold"] = object{"type": "boolean"}
		required = []string{"type", "ticks", "x", "y", "hold"}
	}
	return object{"type": "object", "properties": props, "required": required, "additionalProperties": false}
}
func actionFrom(content string) (object, error) {
	dec := json.NewDecoder(strings.NewReader(content))
	dec.UseNumber()
	var a object
	if err := dec.Decode(&a); err != nil {
		return nil, err
	}
	var extra any
	if err := dec.Decode(&extra); err != io.EOF {
		return nil, errors.New("expected exactly one JSON object")
	}
	if a == nil {
		return nil, errors.New("action object required")
	}
	return a, nil
}
func boolean(m object, key string) bool   { v, _ := m[key].(bool); return v }
func number(m object, key string) float64 { v, _ := m[key].(float64); return v }

type chatResponse struct {
	Message struct {
		Content string `json:"content"`
	} `json:"message"`
	Prompt     int   `json:"prompt_eval_count"`
	Completion int   `json:"eval_count"`
	Duration   int64 `json:"total_duration"`
}

func run() error {
	model := flag.String("model", "qwen2.5:3b", "Ollama model already pulled inside the VM")
	game := flag.String("game", "angry-birds", "angry-birds or getting-over-it")
	level := flag.Int("level", 0, "zero-based level")
	steps := flag.Int("steps", 32, "maximum decisions")
	tokens := flag.Int("tokens", 30000, "total prompt and completion token budget per episode")
	timeout := flag.Duration("timeout", 20*time.Minute, "whole episode deadline")
	envPath := flag.String("env", "/opt/game-research/build/game-env", "trusted environment executable")
	output := flag.String("output", "/var/lib/game-research/results/episode.jsonl", "new trajectory file (never overwritten)")
	flag.Parse()
	if *game != "angry-birds" && *game != "getting-over-it" {
		return errors.New("unsupported game")
	}
	if *steps < 1 || *steps > 10000 || *tokens < 1024 || *tokens > 10000000 || *timeout <= 0 || *timeout > 24*time.Hour {
		return errors.New("invalid episode budget")
	}
	if err := guestCheck(); err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	ctx, cancel := context.WithTimeout(ctx, *timeout)
	defer cancel()
	client := &http.Client{Timeout: 3 * time.Minute, Transport: &http.Transport{Proxy: nil}}
	var tags struct {
		Models []struct {
			Name   string `json:"name"`
			Digest string `json:"digest"`
		} `json:"models"`
	}
	if err := api(ctx, client, "/api/tags", nil, &tags); err != nil {
		return err
	}
	digest := ""
	for _, m := range tags.Models {
		if m.Name == *model || m.Name == *model+":latest" {
			digest = m.Digest
		}
	}
	if digest == "" {
		return fmt.Errorf("model %q is not installed in the guest", *model)
	}
	var capabilities object
	if err := api(ctx, client, "/api/show", object{"model": *model}, &capabilities); err != nil {
		return err
	}
	file, err := os.OpenFile(*output, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	defer file.Close()
	log := json.NewEncoder(file)
	write := func(v object) error {
		if err := log.Encode(v); err != nil {
			return err
		}
		return file.Sync()
	}
	if err = write(object{"event": "metadata", "protocol": 1, "revision": revision, "model": *model, "digest": digest, "capabilities": capabilities["capabilities"], "game": *game, "level": *level, "track": "structured-state", "started": time.Now().UTC(), "max_steps": *steps, "token_budget": *tokens}); err != nil {
		return err
	}
	env, err := startEnvironment(ctx, *envPath)
	if err != nil {
		return err
	}
	defer func() { env.in.Close(); env.cmd.Process.Kill(); env.cmd.Wait() }()
	desc, err := env.call(object{"op": "describe"})
	if err != nil {
		return err
	}
	reset := object{"op": "reset", "game": *game, "level": *level}
	state, err := env.call(reset)
	if err != nil {
		return err
	}
	if !boolean(state, "ok") {
		return fmt.Errorf("reset failed: %v", state)
	}
	if err = write(object{"event": "reset", "request": reset, "response": state}); err != nil {
		return err
	}
	instructions, _ := json.Marshal(desc)
	system := "You control a physics game through ONE JSON action per response. Return only an action matching the schema. No shell, text, or code. Fixed simulation time: ticks/60 seconds. Try to win and use observations to correct your strategy. Angry Birds: negative pull x launches right, positive pull y launches upward, pull length must be <=95. Wait while flying; use ability only if ready. Ascent: aim relative to shoulder; hold to anchor on terrain, then change aim to push/pull your body. Rules: " + string(instructions)
	used, invalid, executed := 0, 0, 0
	reason := "decision_limit"
	last := ""
	started := time.Now()
	for i := 0; i < *steps; i++ {
		if boolean(state, "terminated") || boolean(state, "truncated") {
			reason = "environment_finished"
			break
		}
		// Reserve enough room for the current bounded observation and completion.
		obs, _ := json.Marshal(state)
		if used+len(system)+len(obs)+len(last)+384 > *tokens {
			reason = "token_budget"
			break
		}
		content := string(obs)
		if last != "" {
			content += "\nPrevious attempt: " + last
		}
		body := object{"model": *model, "stream": false, "format": schema(*game), "messages": []object{{"role": "system", "content": system}, {"role": "user", "content": content}}, "options": object{"num_ctx": 8192, "num_predict": 256, "temperature": 0, "seed": 0, "num_thread": 4}, "keep_alive": "5m"}
		var reply chatResponse
		callStart := time.Now()
		if err = api(ctx, client, "/api/chat", body, &reply); err != nil {
			write(object{"event": "error", "step": i, "error": err.Error()})
			return err
		}
		used += reply.Prompt + reply.Completion
		action, decodeErr := actionFrom(reply.Message.Content)
		var response object
		if decodeErr == nil {
			response, err = env.call(object{"op": "act", "action": action})
			if err != nil {
				return err
			}
		}
		entry := object{"event": "step", "step": i, "raw_action": reply.Message.Content, "action": action, "response": response, "prompt_tokens": reply.Prompt, "completion_tokens": reply.Completion, "ollama_duration_ns": reply.Duration, "wall_ms": time.Since(callStart).Milliseconds()}
		if decodeErr != nil {
			entry["error"] = decodeErr.Error()
		}
		if err = write(entry); err != nil {
			return err
		}
		if decodeErr != nil || !boolean(response, "ok") {
			invalid++
			last = fmt.Sprintf("action=%s rejected=%v %v. Correct it.", reply.Message.Content, decodeErr, response)
			if invalid >= 5 {
				reason = "invalid_action_limit"
				break
			}
		} else {
			state = response
			executed++
			last = "action=" + reply.Message.Content
		}
		if used >= *tokens {
			reason = "token_budget"
			break
		}
	}
	summary := object{"event": "summary", "reason": reason, "executed_actions": executed, "invalid_actions": invalid, "tokens": used, "elapsed_ms": time.Since(started).Milliseconds(), "final": state}
	if err = write(summary); err != nil {
		return err
	}
	b, _ := json.Marshal(summary)
	fmt.Println(string(b))
	return nil
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
