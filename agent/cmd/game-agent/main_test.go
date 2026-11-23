package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"
)

func TestActionParsing(t *testing.T) {
	for _, s := range []string{`null`, `{"type":"wait"} {}`, "```json\n{}\n```", `[]`} {
		if _, err := actionFrom(s); err == nil {
			t.Fatalf("accepted %q", s)
		}
	}
	a, err := actionFrom(`{"type":"launch","x":-70,"y":40,"ticks":120}`)
	if err != nil {
		t.Fatal(err)
	}
	if a["type"] != "launch" {
		t.Fatal(a)
	}
}
func TestSchema(t *testing.T) {
	b, _ := json.Marshal(schema("getting-over-it", nil))
	if !strings.Contains(string(b), `"hold"`) {
		t.Fatal(string(b))
	}
}

// Server errors and response size must not escape the HTTP boundary.
func TestAPIRejectsOversizedResponse(t *testing.T) {
	client := &http.Client{Transport: fakeTransport{}}
	var result object
	if api(context.Background(), client, "/api/tags", nil, &result) == nil {
		t.Fatal("accepted oversized response")
	}
}

type fakeTransport struct{}

func (fakeTransport) RoundTrip(q *http.Request) (*http.Response, error) {
	return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(strings.Repeat("x", maxResponse+1))), Header: make(http.Header)}, nil
}

func TestFlyingSchemaExcludesUnavailableActions(t *testing.T) {
	b, _ := json.Marshal(schema("angry-birds", object{"observation": object{"phase": "flying", "ability_ready": false}}))
	if strings.Contains(string(b), "launch") || strings.Contains(string(b), "ability") || strings.Contains(string(b), `"x"`) {
		t.Fatal(string(b))
	}
}
func TestPromptCompactionKeepsOriginal(t *testing.T) {
	original := object{"x": 1.23456789}
	copy := compact(original).(object)
	if original["x"] == copy["x"] {
		t.Fatal("not compacted")
	}
	if original["x"] != 1.23456789 {
		t.Fatal("mutated original")
	}
}
