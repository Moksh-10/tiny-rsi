#include "simulation.h"
#include <raylib.h>
#include <algorithm>
#include <cmath>
#include <string>

namespace {
constexpr int W = 1280, H = 720;
constexpr Color ink{39, 48, 45, 255}, cream{255, 247, 219, 255};
Vector2 vec(b2Vec2 p) { return {p.x, p.y}; }
void text(const char* value, int x, int y, int size, Color color = ink) { DrawText(value, x, y, size, color); }
void bird(Vector2 p, float radius = 19, Color color = {220, 66, 48, 255}) {
    DrawCircleV({p.x + 2, p.y + 4}, radius, {125, 49, 37, 255});
    DrawCircleV(p, radius, color);
    DrawEllipse(static_cast<int>(p.x - 3), static_cast<int>(p.y + 9), radius * .65f, radius * .42f, cream);
    DrawTriangle({p.x + radius + 10, p.y + 2}, {p.x + radius - 4, p.y - 4}, {p.x + radius - 4, p.y + 8}, ORANGE);
    DrawCircleV({p.x + 4, p.y - 4}, radius * .28f, WHITE);
    DrawCircleV({p.x + 6, p.y - 3}, radius * .12f, ink);
    DrawLineEx({p.x - 1, p.y - 12}, {p.x + 11, p.y - 8}, 4, ink);
    DrawLineEx({p.x - 4, p.y - radius + 3}, {p.x - 8, p.y - radius - 7}, 5, color);
}
void pig(Vector2 p, float radius) {
    Color green{139, 184, 64, 255};
    DrawCircleV({p.x - radius * .55f, p.y - radius * .75f}, radius * .3f, green);
    DrawCircleV({p.x + radius * .55f, p.y - radius * .75f}, radius * .3f, green);
    DrawCircleV({p.x + 2, p.y + 3}, radius, {79, 119, 43, 255});
    DrawCircleV(p, radius, green);
    for (float dx : {-0.38f, 0.38f}) {
        DrawCircleV({p.x + radius * dx, p.y - radius * .25f}, radius * .23f, WHITE);
        DrawCircleV({p.x + radius * dx + 1, p.y - radius * .23f}, radius * .09f, ink);
    }
    DrawEllipse(static_cast<int>(p.x), static_cast<int>(p.y + radius * .32f), radius * .49f, radius * .32f, {187, 216, 112, 255});
    for (float dx : {-0.18f, 0.18f}) DrawCircleV({p.x + radius * dx, p.y + radius * .32f}, radius * .09f, {80, 117, 49, 255});
}
void background() {
    ClearBackground({187, 219, 215, 255});
    DrawCircle(1120, 155, 55, {255, 233, 165, 255});
    for (int x : {150, 470, 760}) {
        DrawEllipse(x, 170, 65, 17, {226, 238, 222, 255});
        DrawEllipse(x - 22, 160, 30, 24, {226, 238, 222, 255});
    }
    DrawEllipse(300, 625, 520, 270, {156, 191, 157, 255});
    DrawEllipse(1100, 625, 570, 330, {146, 181, 151, 255});
    DrawEllipse(620, 670, 580, 200, {112, 154, 122, 255});
    DrawRectangle(0, 620, W, 100, {179, 132, 82, 255});
    DrawRectangle(0, 620, W, 12, {79, 117, 66, 255});
    for (int i = 0; i < 65; ++i) DrawCircle((i * 137 + 20) % W, 650 + (i * 19) % 70, 2, {152, 108, 66, 255});
}
void block(const birds::Simulation& game, const birds::Entity& e) {
    auto p = vec(game.position(e));
    float angle = game.angle(e);
    const bool stone = e.kind == birds::Kind::Stone;
    Color base = stone ? Color{132, 148, 146, 255} : Color{193, 132, 66, 255};
    Color edge = stone ? Color{84, 104, 105, 255} : Color{125, 77, 40, 255};
    auto point = [&](float x, float y) -> Vector2 {
        return {p.x + x * std::cos(angle) - y * std::sin(angle), p.y + x * std::sin(angle) + y * std::cos(angle)};
    };
    DrawRectanglePro({p.x, p.y, e.width, e.height}, {e.width / 2, e.height / 2}, angle * RAD2DEG, edge);
    DrawRectanglePro({p.x, p.y, e.width - 5, e.height - 5}, {(e.width - 5) / 2, (e.height - 5) / 2}, angle * RAD2DEG, base);
    if (!stone) {
        if (e.width > e.height) DrawLineEx(point(-e.width / 2 + 8, 0), point(e.width / 2 - 8, 0), 2, {221, 163, 92, 255});
        else DrawLineEx(point(0, -e.height / 2 + 8), point(0, e.height / 2 - 8), 2, {221, 163, 92, 255});
    }
    if (e.health < e.maxHealth * .65f) {
        DrawLineEx(point(-4, -e.height * .35f), point(4, 0), 2, edge);
        DrawLineEx(point(4, 0), point(-3, e.height * .3f), 2, edge);
    }
}
}

int main(int argc, char** argv) {
    bool smoke = false;
    for (int i = 1; i < argc; ++i) if (std::string(argv[i]) == "--smoke-test") smoke = true;
    SetConfigFlags(FLAG_WINDOW_RESIZABLE | FLAG_MSAA_4X_HINT);
    InitWindow(W, H, "Angry Birds | Slingshot Valley");
    SetWindowMinSize(800, 450);
    SetTargetFPS(60);
    auto target = LoadRenderTexture(W, H);
    SetTextureFilter(target.texture, TEXTURE_FILTER_BILINEAR);
    birds::Simulation game;
    bool dragging = false, paused = false;
    Vector2 pull{};
    int frames = 0;
    while (!WindowShouldClose()) {
        float zoom = std::min(GetScreenWidth() / float(W), GetScreenHeight() / float(H));
        Vector2 offset{(GetScreenWidth() - W * zoom) / 2, (GetScreenHeight() - H * zoom) / 2};
        auto mouse = GetMousePosition();
        mouse = {(mouse.x - offset.x) / zoom, (mouse.y - offset.y) / zoom};
        if (IsKeyPressed(KEY_R) || (IsMouseButtonPressed(MOUSE_BUTTON_LEFT) && CheckCollisionPointRec(mouse, {1120, 28, 125, 44}))) {
            game.reset(); dragging = paused = false; pull = {};
        }
        if (IsKeyPressed(KEY_P)) { paused = !paused; dragging = false; pull = {}; }
        if (!paused && game.phase() == birds::Phase::Aiming) {
            if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT) && CheckCollisionPointCircle(mouse, vec(birds::sling), 55)) dragging = true;
            if (dragging) {
                pull = {mouse.x - birds::sling.x, mouse.y - birds::sling.y};
                float len = std::hypot(pull.x, pull.y);
                if (len > 95) { pull.x *= 95 / len; pull.y *= 95 / len; }
                if (IsMouseButtonReleased(MOUSE_BUTTON_LEFT)) { game.launch({pull.x, pull.y}); dragging = false; pull = {}; }
            }
        }
        if (!paused) game.step(GetFrameTime());
        BeginTextureMode(target);
        background();
        text("SLINGSHOT / VALLEY", 36, 27, 29);
        text("01  /  THE TIMBER FORT", 38, 64, 16, {66, 101, 89, 255});
        DrawRectangleRounded({580, 24, 505, 60}, .2f, 8, Fade(cream, .8f));
        text(TextFormat("SCORE  %05i", game.score()), 600, 45, 22);
        text(TextFormat("PIGS  %i", game.pigsLeft()), 810, 45, 22);
        text(TextFormat("BIRDS  %i", game.birdsLeft()), 950, 45, 22);
        DrawRectangleRounded({1120, 28, 125, 44}, .2f, 8, ink);
        text("RETRY  R", 1138, 42, 19, cream);
        // Slingshot back arm and elastic.
        DrawLineEx({210, 610}, {210, 488}, 19, {100, 65, 43, 255});
        DrawLineEx({210, 491}, {187, 432}, 15, {100, 65, 43, 255});
        Vector2 held{birds::sling.x + pull.x, birds::sling.y + pull.y};
        if (game.phase() == birds::Phase::Aiming) {
            DrawLineEx({187, 437}, held, 6, {70, 47, 38, 255});
            if (dragging) {
                const float vx = -pull.x * .26f * birds::scale;
                const float vy = -pull.y * .26f * birds::scale;
                for (int i = 1; i <= 24; ++i) {
                    float t = i * .075f;
                    Vector2 dot{held.x + vx * t, held.y + vy * t + .5f * 9.8f * birds::scale * t * t};
                    if (dot.y > 615 || dot.x > W || dot.x < 0) break;
                    DrawCircleV(dot, 3, Fade(cream, 1 - i / 30.0f));
                }
            }
            bird(held);
        }
        for (const auto& e : game.entities()) {
            if (!e.alive) continue;
            auto p = vec(game.position(e));
            if (e.kind == birds::Kind::Pig) pig(p, e.width / 2);
            else if (e.kind == birds::Kind::Bird) bird(p);
            else block(game, e);
        }
        DrawLineEx({210, 491}, {235, 433}, 15, {137, 90, 49, 255});
        if (game.phase() == birds::Phase::Aiming) DrawLineEx({235, 438}, held, 5, {89, 55, 39, 255});
        int queued = game.birdsLeft() - (game.phase() == birds::Phase::Aiming ? 1 : 0);
        for (int i = 0; i < queued; ++i) bird({70.0f + i * 46, 600}, 15);
        DrawRectangleRounded({360, 650, 740, 43}, .25f, 8, Fade(cream, .92f));
        const char* hint = dragging ? "RELEASE TO LAUNCH  /  Pull further for more power" : game.phase() == birds::Phase::Flying ? "WATCH THE FORT FALL  /  Next bird loads when the scene settles" : "DRAG THE BIRD BACK, THEN RELEASE  /  P pause  /  R restart";
        text(hint, 382, 664, 18);
        const bool won = game.phase() == birds::Phase::Won;
        const bool lost = game.phase() == birds::Phase::Lost;
        if (paused || won || lost) {
            DrawRectangle(0, 100, W, 520, Fade(ink, .55f));
            DrawRectangleRounded({400, 240, 480, 210}, .09f, 8, cream);
            text(paused ? "TAKE A BREATHER" : won ? "FORT DEMOLISHED!" : "ONE MORE SHOT?", 438, 278, 32);
            text(paused ? "Press P to resume" : won ? TextFormat("Final score: %i", game.score()) : "The pigs held their ground.", 440, 337, 23);
            text(paused ? "R to start fresh" : "Press R or click RETRY to play again", 440, 393, 19);
        }
        EndTextureMode();
        BeginDrawing();
        ClearBackground(ink);
        DrawTexturePro(target.texture, {0, 0, float(W), -float(H)}, {offset.x, offset.y, W * zoom, H * zoom}, {0, 0}, 0, WHITE);
        EndDrawing();
        if (smoke && ++frames >= 60) break;
    }
    UnloadRenderTexture(target);
    CloseWindow();
}
