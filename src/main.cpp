#include "presentation.h"
#include "progress.h"
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace birds;
enum class Screen { Home, Map, Game, Pause, Result, Help };
constexpr Color green{100, 175, 49, 255}, orange{237, 148, 43, 255};
Vector2 point(b2Vec2 p) {
    return {p.x, p.y};
}
class Application {
  public:
    Application(const std::filesystem::path &assets, const std::filesystem::path &save, bool demo)
        : art(assets), savePath(save), demoMode(demo) {
        if (!demoMode)
            progress.load(savePath);
        selectedWorld = std::min(2, (progress.unlockedCount() - 1) / 4);
    }
    void frame(float dt, Vector2 mouse);
    void start(int level);
    void renderPreview(const std::string &name);
    void testFlow();
    bool quitting{};

  private:
    Art art;
    Audio audio;
    Simulation game;
    Progress progress;
    Effects effects;
    std::filesystem::path savePath;
    bool demoMode{}, dragging{}, savedResult{}, saveFailed{}, wasFocused{true}, abilityRequested{};
    Screen screen{Screen::Home}, helpReturn{Screen::Home};
    int selectedWorld{}, hoveredLevel{-1};
    Vector2 pull{}, pointerOrigin{};
    float clock{}, screenTime{}, playTime{}, resultTimer{}, shownScore{}, hitCooldown{};
    std::vector<Vector2> trail;
    void go(Screen next) {
        screen = next;
        screenTime = 0;
        dragging = false;
        pull = {};
    }
    void save() {
        if (!demoMode)
            saveFailed = !progress.save(savePath);
    }
    void click() { audio.play(Cue::Click, progress.muted); }
    void home(Vector2 mouse, bool pressed);
    void map(Vector2 mouse, bool pressed);
    void playfield();
    void hud(Vector2 mouse, bool pressed);
    void overlay(Vector2 mouse, bool pressed);
    void help(Vector2 mouse, bool pressed);
    void shootInput(Vector2 mouse);
    bool button(Rectangle r, const char *text, Vector2 mouse, bool pressed, Color color = green,
                bool enabled = true) {
        if (art.button(r, text, mouse, pressed, color, enabled)) {
            click();
            return true;
        }
        return false;
    }
    bool icon(Vector2 p, int value, Vector2 mouse, bool pressed, bool active = false) {
        if (art.iconButton(p, value, mouse, pressed, active)) {
            click();
            return true;
        }
        return false;
    }
};
void Application::start(int level) {
    game.loadLevel(level);
    effects.clear();
    trail.clear();
    savedResult = false;
    playTime = resultTimer = shownScore = 0;
    go(Screen::Game);
}
void Application::renderPreview(const std::string &name) {
    const Vector2 outside{-1000, -1000};
    clock = 2;
    screenTime = 2;
    if (name == "icon") {
        ClearBackground({52, 161, 194, 255});
        DrawCircle(640, 360, 340, {251, 203, 58, 255});
        art.bird({640, 380}, 230, BirdType::Red, -10);
    } else if (name == "home") {
        go(Screen::Home);
        home(outside, false);
    } else if (name == "map" || name == "canyon" || name == "night") {
        selectedWorld = name == "canyon" ? 1 : name == "night" ? 2 : 0;
        for (int i = 0; i < selectedWorld * 4 + 2; i++)
            progress.complete(i, 3, 9000);
        go(Screen::Map);
        map(outside, false);
    } else if (name == "help") {
        help(outside, false);
    } else {
        start(name == "game" ? 3 : name.starts_with("level-") ? std::stoi(name.substr(6)) - 1 : 0);
        playTime = 4;
        if (name == "result") {
            for (auto pull : {b2Vec2{-85, 5}, b2Vec2{-95, -15}}) {
                if (game.phase() == Phase::Won)
                    break;
                game.launch(pull);
                for (int i = 0; i < 660; i++)
                    game.step(1.0f / 60);
            }
            go(Screen::Result);
            screenTime = 2;
            overlay(outside, false);
        } else if (name == "pause") {
            go(Screen::Pause);
            overlay(outside, false);
        } else {
            playfield();
            hud(outside, false);
        }
    }
}
void Application::testFlow() {
    auto expect = [](bool condition, const char *message) {
        if (!condition)
            throw std::runtime_error(message);
    };
    const Vector2 outside{-1000, -1000};
    home({250, 530}, true);
    expect(screen == Screen::Game && game.levelIndex() == 0, "home play opens first level");
    hud({46, 45}, true);
    expect(screen == Screen::Pause, "pause button opens pause screen");
    overlay({640, 400}, true);
    expect(screen == Screen::Game, "resume returns to game");
    game.launch({-85, 5});
    hud({110, 45}, true);
    expect(game.phase() == Phase::Aiming && game.birdsLeft() == 3, "HUD retry resets level");
    for (auto pull : {b2Vec2{-85, 5}, b2Vec2{-95, -15}}) {
        if (game.phase() == Phase::Won)
            break;
        game.launch(pull);
        for (int i = 0; i < 660; i++)
            game.step(1.0f / 60);
    }
    frame(.016f, outside);
    frame(1.3f, outside);
    expect(screen == Screen::Result && progress.unlocked(1), "win opens results and unlocks next level");
    overlay({640, 486}, true);
    expect(screen == Screen::Game && game.levelIndex() == 1, "next level button advances campaign");
    go(Screen::Pause);
    overlay({727, 479}, true);
    expect(screen == Screen::Map, "pause levels button opens map");
    map({1040, 330}, true);
    expect(screen == Screen::Map, "locked map node stays locked");
    map({505, 325}, true);
    expect(screen == Screen::Game && game.levelIndex() == 1, "unlocked map node starts selected level");
    go(Screen::Pause);
    overlay({640, 563}, true);
    expect(screen == Screen::Help, "help opens from pause");
    help({640, 584}, true);
    expect(screen == Screen::Pause, "help returns to pause");
    overlay({719, 563}, true);
    expect(screen == Screen::Home, "home button returns to title screen");
    const bool oldMute = progress.muted;
    home({1218, 54}, true);
    expect(progress.muted != oldMute, "sound toggle works");
    start(0);
    for (int shot = 0; shot < 3; shot++) {
        game.launch({-10, 0});
        for (int i = 0; i < 660; i++)
            game.step(1.0f / 60);
    }
    frame(.016f, outside);
    frame(1.3f, outside);
    expect(screen == Screen::Result && game.phase() == Phase::Lost, "loss opens retry result screen");
    overlay({640, 486}, true);
    expect(screen == Screen::Game && game.birdsLeft() == 3, "try again restores flock");
    std::cout << "UI flow checks passed: play, pause, resume, retry, win, unlock, next level, map, help, "
                 "sound, loss\n";
}
void Application::home(Vector2 mouse, bool pressed) {
    art.background(0, clock, true);
    art.label("THE FLOCK IS BACK.", 100, 99, 21, paper);
    art.title("ANGRY", 100, 139, 112);
    art.title("BIRDS", 100, 238, 134);
    DrawRectangleRounded({102, 383, 285, 37}, .2f, 8, {243, 186, 49, 255});
    art.label("SLINGSHOT VALLEY", 245, 388, 28, outline, true, true);
    art.label("Small birds. Big trouble.", 104, 437, 25, paper);
    const int next = std::min(levelCount - 1, progress.unlockedCount() - 1);
    if (button({104, 491, 290, 78}, progress.totalStars() > 0 ? "CONTINUE" : "LET'S PLAY", mouse, pressed))
        start(next);
    if (button({104, 592, 290, 54}, "CHOOSE LEVEL", mouse, pressed, orange))
        go(Screen::Map);
    if (icon({1218, 54}, 4, mouse, pressed, progress.muted)) {
        progress.muted = !progress.muted;
        save();
    }
    if (icon({1150, 54}, 6, mouse, pressed)) {
        helpReturn = Screen::Home;
        go(Screen::Help);
    }
    // Layered character composition, with silhouettes and shadows grounded in the landscape.
    DrawEllipse(847, 606, 225, 23, Fade(outline, .22f));
    art.bird({770, 433 + std::sin(clock * 1.7f) * 7}, 110, BirdType::Red, -12);
    art.bird({1004, 437 + std::sin(clock * 1.7f + 1) * 6}, 72, BirdType::Dash, 9);
    art.bird({923, 550 + std::sin(clock * 1.7f + 2) * 4}, 73, BirdType::Bomb, 8);
    art.pig({1168, 591}, 26, -8);
    DrawRectangleRounded({722, 141, 390, 56}, .3f, 10, Fade(outline, .65f));
    art.label("12 LEVELS. 3 WORLDS. TOTAL CHAOS.", 917, 156, 20, paper, false, true);
    art.star({1062, 255}, 30, true);
    art.star({1120, 340}, 19, true);
    if (progress.totalStars() > 0) {
        art.star({1068, 53}, 15, true);
        art.label(TextFormat("%i / 36", progress.totalStars()), 1010, 79, 16, paper);
    }
    art.label("DRAG TO AIM  /  RELEASE TO FLY", 1070, 675, 16, paper, false, true);
    art.label("EXIT", 104, 675, 17, paper);
    if (pressed && CheckCollisionPointRec(mouse, {100, 665, 65, 36}))
        quitting = true;
    if (IsKeyPressed(KEY_ENTER) || IsKeyPressed(KEY_SPACE))
        start(next);
}
void Application::map(Vector2 mouse, bool pressed) {
    art.background(selectedWorld, clock);
    DrawRectangleGradientV(0, 0, 1280, 220, Fade(outline, .6f), Fade(outline, 0));
    if (icon({52, 50}, 2, mouse, pressed))
        go(Screen::Home);
    if (icon({1220, 50}, 4, mouse, pressed, progress.muted)) {
        progress.muted = !progress.muted;
        save();
    }
    art.star({1048, 50}, 18, true);
    art.title(TextFormat("%i / 36", progress.totalStars()), 1080, 30, 30);
    const char *names[]{"GREENWOOD GROVE", "SUNSET CANYON", "MOONLIGHT RIDGE"};
    art.label(TextFormat("CHAPTER %02i", selectedWorld + 1), 640, 72, 18, paper, false, true);
    art.title(names[selectedWorld], 640, 102, 66, paper, true);
    art.label("A little aim. A lot of destruction.", 640, 181, 22, paper, false, true);
    const Vector2 nodes[]{{240, 385}, {505, 325}, {770, 400}, {1040, 330}};
    for (int i = 0; i < 3; i++) {
        DrawLineBezier(nodes[i], nodes[i + 1], 14, Fade(outline, .5f));
        DrawLineBezier(nodes[i], nodes[i + 1], 8, {244, 218, 157, 255});
    }
    hoveredLevel = -1;
    for (int i = 0; i < 4; i++) {
        int index = selectedWorld * 4 + i;
        auto p = nodes[i];
        bool unlocked = progress.unlocked(index), hover = CheckCollisionPointCircle(mouse, p, 51);
        bool current = index == progress.unlockedCount() - 1;
        if (hover)
            hoveredLevel = index;
        if (current)
            DrawRing(p, 57 + std::sin(clock * 3) * 2, 61 + std::sin(clock * 3) * 2, 0, 360, 64,
                     Fade(gold, .8f));
        DrawCircleV({p.x, p.y + 8}, 52, Fade(outline, .6f));
        DrawCircleV(p, 52, outline);
        DrawCircleV(p, 48,
                    unlocked ? (hover ? Color{253, 213, 82, 255} : Color{232, 175, 66, 255})
                             : Color{118, 131, 120, 255});
        DrawCircleV({p.x, p.y - 3}, 43, unlocked ? Color{251, 207, 96, 255} : Color{142, 153, 139, 255});
        if (unlocked)
            art.title(TextFormat("%02i", index + 1), p.x, p.y - 31, 55, paper, true);
        else {
            DrawRectangleRounded({p.x - 13, p.y - 5, 26, 23}, .2f, 8, Fade(outline, .6f));
            DrawRing({p.x, p.y - 7}, 8, 12, 180, 360, 20, Fade(outline, .6f));
        }
        art.stars({p.x, p.y + 68}, progress.records[index].stars, 13);
        DrawRectangleRounded({p.x - 105, p.y + 94, 210, 31}, .4f, 8, Fade(outline, .7f));
        art.label(levels()[index].name, p.x, p.y + 98, 18, paper, false, true);
        if (hover && pressed && unlocked) {
            click();
            start(index);
        }
    }
    int info = hoveredLevel >= 0
                   ? hoveredLevel
                   : std::clamp(progress.unlockedCount() - 1, selectedWorld * 4, selectedWorld * 4 + 3);
    DrawRectangleRounded({310, 554, 660, 58}, .3f, 10, Fade(outline, .72f));
    art.label(progress.unlocked(info) ? levels()[info].hint : "Clear the previous level to unlock this one.",
              640, 572, 20, paper, false, true);
    for (int i = 0; i < 3; i++) {
        Rectangle r{380 + i * 180.0f, 649, 160, 43};
        if (art.button(r, TextFormat("CHAPTER %i", i + 1), mouse, pressed,
                       i == selectedWorld ? green : Color{119, 142, 112, 255}, true, false)) {
            click();
            selectedWorld = i;
        }
    }
    if (IsKeyPressed(KEY_LEFT))
        selectedWorld = std::max(0, selectedWorld - 1);
    if (IsKeyPressed(KEY_RIGHT))
        selectedWorld = std::min(2, selectedWorld + 1);
    if (IsKeyPressed(KEY_ENTER))
        start(std::min(levelCount - 1, progress.unlockedCount() - 1));
}
void Application::shootInput(Vector2 mouse) {
    if (game.phase() != Phase::Aiming)
        return;
    if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT) && CheckCollisionPointCircle(mouse, point(sling), 53))
        dragging = true;
    if (dragging) {
        if (!IsWindowFocused()) {
            dragging = false;
            pull = {};
            return;
        }
        pull = {mouse.x - sling.x, mouse.y - sling.y};
        float len = std::hypot(pull.x, pull.y);
        if (len > 95) {
            pull.x *= 95 / len;
            pull.y *= 95 / len;
        }
        if (IsMouseButtonReleased(MOUSE_BUTTON_LEFT)) {
            if (game.launch({pull.x, pull.y})) {
                audio.play(Cue::Launch, progress.muted);
                trail.clear();
            }
            dragging = false;
            pull = {};
        }
    }
}
void Application::playfield() {
    art.background(game.definition().theme, clock);
    Camera2D camera{};
    camera.zoom = 1;
    if (effects.shake > .1f)
        camera.offset = {std::sin(clock * 111) * effects.shake, std::cos(clock * 139) * effects.shake * .6f};
    BeginMode2D(camera);
    for (size_t i = 0; i < trail.size(); i += 4)
        DrawCircleV(trail[i], 2, Fade(paper, .45f));
    // Sculpted, outlined slingshot with separate front and back elastic.
    DrawEllipse(210, 619, 40, 9, Fade(outline, .25f));
    DrawLineEx({210, 616}, {208, 492}, 22, outline);
    DrawLineEx({210, 615}, {208, 492}, 16, {133, 83, 39, 255});
    DrawLineEx({206, 608}, {204, 501}, 4, {196, 136, 66, 255});
    DrawLineEx({208, 497}, {186, 432}, 20, outline);
    DrawLineEx({208, 497}, {186, 432}, 14, {136, 85, 41, 255});
    Vector2 held{sling.x + pull.x, sling.y + pull.y};
    const bool aiming = game.phase() == Phase::Aiming;
    if (aiming) {
        DrawLineEx({186, 438}, held, 8, {56, 36, 29, 255});
        DrawLineEx({186, 436}, held, 3, {125, 76, 43, 255});
        if (dragging) {
            float vx = -pull.x * .26f * scale, vy = -pull.y * .26f * scale;
            for (int i = 1; i <= 32; i++) {
                float t = i * .055f;
                Vector2 dot{held.x + vx * t, held.y + vy * t + .5f * 9.8f * scale * t * t};
                if (dot.y > 615 || dot.x > 1280 || dot.x < 0)
                    break;
                DrawCircleV(dot, 3.6f - i * .06f, Fade(paper, 1 - i / 39.0f));
            }
        }
        art.bird(held, 20, game.nextBird());
    }
    for (const auto &e : game.entities()) {
        if (!e.alive)
            continue;
        if (e.kind == Kind::Bird)
            art.bird(point(game.position(e)), e.width / 2, e.bird, game.angle(e) * RAD2DEG,
                     game.phase() == Phase::Flying);
        else if (e.kind == Kind::Pig)
            art.pig(point(game.position(e)), e.width / 2, game.angle(e) * RAD2DEG,
                    e.health < e.maxHealth * .6f);
        else
            art.block(game, e);
    }
    DrawLineEx({208, 496}, {236, 432}, 20, outline);
    DrawLineEx({208, 496}, {236, 432}, 14, {163, 105, 52, 255});
    DrawLineEx({213, 488}, {233, 438}, 3, {219, 163, 90, 255});
    if (aiming) {
        DrawLineEx({236, 438}, held, 7, {68, 41, 28, 255});
        DrawLineEx({236, 436}, held, 2, {153, 94, 52, 255});
    }
    for (int i = 0; i < game.birdsLeft() - (aiming ? 1 : 0); i++) {
        int slot = 3 - game.birdsLeft() + (aiming ? 1 : 0) + i;
        art.bird({76.0f + i * 47, 601}, 15, game.definition().flock[std::min(2, slot)]);
    }
    effects.draw(art);
    EndMode2D();
}
void Application::hud(Vector2 mouse, bool pressed) {
    DrawRectangleGradientV(0, 0, 1280, 125, Fade(Color{26, 35, 39, 255}, .45f), Fade(outline, 0));
    if (icon({46, 45}, 0, mouse, pressed)) {
        go(Screen::Pause);
        return;
    }
    if (icon({110, 45}, 1, mouse, pressed)) {
        start(game.levelIndex());
        return;
    }
    art.label(TextFormat("LEVEL %02i", game.levelIndex() + 1), 640, 21, 17, paper, false, true);
    art.title(game.definition().name, 640, 44, 36, paper, true);
    art.label("SCORE", 1207, 21, 14, paper, false, true);
    art.title(TextFormat("%05i", static_cast<int>(shownScore)), 1218, 39, 38, paper, true);
    art.pig({1032, 51}, 15);
    art.title(TextFormat("x%i", game.pigsLeft()), 1075, 37, 28);
    for (int i = 0; i < 3; i++) {
        Rectangle card{29 + i * 68.0f, 646, 59, 58};
        bool spent = i < 3 - game.birdsLeft();
        bool next = i == 3 - game.birdsLeft() && game.phase() == Phase::Aiming;
        DrawRectangleRounded({card.x, card.y + 3, card.width, card.height}, .22f, 8, Fade(outline, .65f));
        DrawRectangleRounded(card, .22f, 8, spent ? Color{108, 108, 93, 180} : next ? gold : paper);
        art.bird({card.x + 29, card.y + 31}, 18, game.definition().flock[i]);
        if (spent) {
            DrawRectangleRounded(card, .22f, 8, Fade(outline, .45f));
            DrawLineEx({card.x + 17, card.y + 28}, {card.x + 25, card.y + 36}, 3, paper);
            DrawLineEx({card.x + 25, card.y + 36}, {card.x + 42, card.y + 17}, 3, paper);
        }
    }
    if (game.abilityReady()) {
        if (button({1008, 649, 242, 50}, "SPACE: ABILITY", mouse, pressed, orange)) {
            abilityRequested = true;
        }
    } else if (game.phase() == Phase::Aiming && playTime < 7) {
        DrawRectangleRounded({440, 651, 485, 43}, .3f, 8, Fade(outline, .7f));
        art.label(dragging ? "Release to fly!" : "Drag the bird back, then release", 682, 662, 20, paper,
                  false, true);
    }
    if (playTime < 2) {
        float alpha = std::min(1.0f, (2 - playTime) * 2);
        art.title(TextFormat("%02i  /  %s", game.levelIndex() + 1, game.definition().name), 640, 151, 48,
                  Fade(paper, alpha), true);
    }
    if (IsKeyPressed(KEY_R))
        start(game.levelIndex());
    if (IsKeyPressed(KEY_P))
        go(Screen::Pause);
}
void Application::overlay(Vector2 mouse, bool pressed) {
    playfield();
    DrawRectangle(0, 0, 1280, 720, Fade(Color{22, 30, 45, 255}, .64f));
    bool pause = screen == Screen::Pause, won = game.phase() == Phase::Won;
    Rectangle panel{390, 113, 500, 514};
    art.panel(panel);
    DrawRectangleRounded({427, 91, 426, 69}, .22f, 12, outline);
    DrawRectangleRounded({431, 89, 418, 63}, .22f, 12,
                         pause ? Color{87, 148, 144, 255}
                         : won ? green
                               : Color{213, 91, 62, 255});
    art.title(pause ? "TAKE A BREATHER"
              : won ? "LEVEL CLEARED!"
                    : "THE PIGS WIN...",
              640, 103, 46, paper, true);
    if (pause) {
        art.bird({640, 246}, 49, game.nextBird(), -8);
        art.label("Your flock can wait a moment.", 640, 319, 22, outline, false, true);
        if (button({476, 370, 328, 62}, "KEEP PLAYING", mouse, pressed))
            go(Screen::Game);
        if (button({476, 453, 151, 56}, "RETRY", mouse, pressed, orange))
            start(game.levelIndex());
        if (button({650, 453, 154, 56}, "LEVELS", mouse, pressed, {98, 148, 159, 255})) {
            selectedWorld = game.levelIndex() / 4;
            go(Screen::Map);
        }
        if (icon({561, 563}, 4, mouse, pressed, progress.muted)) {
            progress.muted = !progress.muted;
            save();
        }
        if (icon({640, 563}, 6, mouse, pressed)) {
            helpReturn = Screen::Pause;
            go(Screen::Help);
        }
        if (icon({719, 563}, 2, mouse, pressed))
            go(Screen::Home);
        if (IsKeyPressed(KEY_P) || IsKeyPressed(KEY_ENTER))
            go(Screen::Game);
    } else {
        if (won) {
            int animatedStars = std::min(game.stars(), static_cast<int>(screenTime * 4));
            art.stars({640, 230}, animatedStars, 43, 110);
            art.label("LEVEL SCORE", 640, 301, 17, {127, 105, 76, 255}, false, true);
            art.title(TextFormat("%05i", game.score()), 640, 322, 67, outline, true);
            art.label(game.levelIndex() == levelCount - 1 ? "All 12 levels cleared. What a flock!"
                                                          : "Nice shot. The next challenge is waiting.",
                      640, 408, 20, outline, false, true);
            if (button({476, 454, 328, 64},
                       game.levelIndex() == levelCount - 1 ? "BACK TO CAMPAIGN" : "NEXT LEVEL", mouse,
                       pressed)) {
                if (game.levelIndex() == levelCount - 1) {
                    selectedWorld = 2;
                    go(Screen::Map);
                } else
                    start(game.levelIndex() + 1);
            }
        } else {
            art.pig({640, 239}, 55, 5);
            art.label("A different angle changes everything.", 640, 326, 21, outline, false, true);
            art.label(TextFormat("Score: %i", game.score()), 640, 367, 24, outline, false, true);
            if (button({476, 454, 328, 64}, "TRY AGAIN", mouse, pressed, orange))
                start(game.levelIndex());
        }
        if (button({477, 548, 150, 49}, "LEVELS", mouse, pressed, {98, 148, 159, 255})) {
            selectedWorld = game.levelIndex() / 4;
            go(Screen::Map);
        }
        if (button({652, 548, 152, 49}, "REPLAY", mouse, pressed, orange))
            start(game.levelIndex());
        if (IsKeyPressed(KEY_ENTER)) {
            if (won && game.levelIndex() < levelCount - 1)
                start(game.levelIndex() + 1);
            else
                start(game.levelIndex());
        }
        if (IsKeyPressed(KEY_R))
            start(game.levelIndex());
        effects.draw(art);
    }
}
void Application::help(Vector2 mouse, bool pressed) {
    art.background(0, clock);
    DrawRectangle(0, 0, 1280, 720, Fade(outline, .45f));
    art.panel({170, 85, 940, 550});
    art.title("MEET YOUR FLOCK", 640, 110, 59, outline, true);
    const char *names[]{"RED", "DASH", "BOMB"};
    const char *descriptions[]{"The original troublemaker.", "Speed through fragile glass.",
                               "Bring the whole house down."};
    const char *actions[]{"Pull back and release.", "SPACE in flight to boost.",
                          "SPACE in flight to explode."};
    for (int i = 0; i < 3; i++) {
        float x = 340 + i * 300.0f;
        art.bird({x, 277}, 55, static_cast<BirdType>(i));
        art.label(names[i], x, 363, 34, outline, true, true);
        art.label(descriptions[i], x, 414, 18, outline, false, true);
        art.label(actions[i], x, 447, 18, outline, false, true);
    }
    art.label("Pop every pig to win. Spare birds earn bonus points. Chase all three stars.", 640, 511, 21,
              outline, false, true);
    if (button({496, 557, 288, 55}, "GOT IT!", mouse, pressed))
        go(helpReturn);
    if (IsKeyPressed(KEY_ENTER))
        go(helpReturn);
}
void Application::frame(float dt, Vector2 mouse) {
    clock += dt;
    screenTime += dt;
    hitCooldown = std::max(0.0f, hitCooldown - dt);
    if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT))
        pointerOrigin = mouse;
    bool pressed = IsMouseButtonReleased(MOUSE_BUTTON_LEFT) && !dragging &&
                   std::hypot(mouse.x - pointerOrigin.x, mouse.y - pointerOrigin.y) < 24;
    bool focused = IsWindowFocused();
    if (!focused && wasFocused && screen == Screen::Game)
        go(Screen::Pause);
    wasFocused = focused;
    if (IsKeyPressed(KEY_ESCAPE)) {
        if (screen == Screen::Game)
            go(Screen::Pause);
        else if (screen == Screen::Pause)
            go(Screen::Game);
        else if (screen == Screen::Help)
            go(helpReturn);
        else if (screen == Screen::Home)
            quitting = true;
        else
            go(Screen::Home);
        pressed = false;
    }
    if (IsKeyPressed(KEY_M)) {
        progress.muted = !progress.muted;
        save();
    }
    effects.update(dt);
    audio.update(screen == Screen::Map ? selectedWorld
                 : (screen == Screen::Game || screen == Screen::Pause || screen == Screen::Result)
                     ? game.definition().theme
                     : 0,
                 progress.muted);
    if (screen == Screen::Game) {
        playTime += dt;
        game.step(dt);
        if (abilityRequested || IsKeyPressed(KEY_SPACE) ||
            (IsMouseButtonPressed(MOUSE_BUTTON_LEFT) && mouse.y < 620 &&
             !CheckCollisionPointCircle(mouse, {46, 45}, 30) &&
             !CheckCollisionPointCircle(mouse, {110, 45}, 30))) {
            if (game.activateAbility())
                audio.play(Cue::Ability, progress.muted);
            abilityRequested = false;
        }
        effects.consume(game.feedback());
        for (auto f : game.feedback()) {
            if (f.kind == Kind::Pig && f.points)
                audio.play(Cue::Pop, progress.muted);
            else if (f.kind == Kind::Tnt) {
                audio.play(Cue::Boom, progress.muted);
                hitCooldown = .12f;
            } else if (hitCooldown <= 0) {
                audio.play(Cue::Hit, progress.muted);
                hitCooldown = .1f;
            }
        }
        if (game.phase() == Phase::Flying) {
            for (auto it = game.entities().rbegin(); it != game.entities().rend(); ++it)
                if (it->alive && it->kind == Kind::Bird) {
                    if (trail.size() < 900)
                        trail.push_back(point(game.position(*it)));
                    break;
                }
        }
        shownScore += (game.score() - shownScore) * std::min(1.0f, dt * 9);
        if (std::abs(game.score() - shownScore) < 1)
            shownScore = static_cast<float>(game.score());
        if (game.phase() == Phase::Won || game.phase() == Phase::Lost) {
            resultTimer += dt;
            if (!savedResult) {
                savedResult = true;
                if (game.phase() == Phase::Won) {
                    progress.complete(game.levelIndex(), game.stars(), game.score());
                    save();
                    audio.play(Cue::Win, progress.muted);
                    effects.confetti();
                } else
                    audio.play(Cue::Lose, progress.muted);
            }
            if (resultTimer > 1.2f)
                go(Screen::Result);
        } else
            shootInput(mouse);
    }
    switch (screen) {
    case Screen::Home:
        home(mouse, pressed);
        break;
    case Screen::Map:
        map(mouse, pressed);
        break;
    case Screen::Game:
        playfield();
        hud(mouse, pressed);
        break;
    case Screen::Pause:
    case Screen::Result:
        overlay(mouse, pressed);
        break;
    case Screen::Help:
        help(mouse, pressed);
        break;
    }
    if (saveFailed) {
        DrawRectangleRounded({340, 10, 600, 35}, .3f, 8, outline);
        art.label("Progress could not be saved. Check your user-data folder is writable.", 640, 17, 17, paper,
                  false, true);
    }
}
} // namespace
int main(int argc, char **argv) {
    bool smoke = false, demo = false, testUI = false;
    int startLevel = -1;
    std::filesystem::path previewDirectory;
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--smoke-test")
            smoke = demo = true;
        else if (arg == "--test-ui")
            testUI = demo = true;
        else if (arg == "--demo")
            demo = true;
        else if (arg == "--render-previews" && i + 1 < argc) {
            previewDirectory = argv[++i];
            demo = true;
        } else if (arg == "--level" && i + 1 < argc) {
            try {
                std::string number = argv[++i];
                size_t count{};
                startLevel = std::stoi(number, &count) - 1;
                if (count != number.size() || startLevel < 0 || startLevel >= levelCount)
                    return 2;
            } catch (...) {
                return 2;
            }
        } else
            return 2;
    }
    if (startLevel >= levelCount || startLevel < -1)
        return 2;
    SetTraceLogLevel(LOG_WARNING);
    SetConfigFlags(FLAG_WINDOW_RESIZABLE | FLAG_MSAA_4X_HINT | FLAG_VSYNC_HINT);
    InitWindow(screenWidth, screenHeight, "Angry Birds - Slingshot Valley");
    if (!IsWindowReady()) {
        std::cerr << "A working OpenGL display is required to start Slingshot Valley.\n";
        return 1;
    }
    SetWindowMinSize(960, 540);
    SetExitKey(KEY_NULL);
    SetTargetFPS(60);
    auto target = LoadRenderTexture(screenWidth, screenHeight);
    SetTextureFilter(target.texture, TEXTURE_FILTER_BILINEAR);
    std::filesystem::path appDirectory = GetApplicationDirectory();
    auto assets = appDirectory / "assets";
    if (!std::filesystem::exists(assets))
        assets = ASSET_SOURCE_DIR;
    for (const auto *required : {"meadow.png", "canyon.png", "night.png", "characters.png", "materials.png",
                                 "Bangers-Regular.ttf", "Nunito-Bold.ttf"}) {
        if (!std::filesystem::is_regular_file(assets / required)) {
            std::cerr << "Missing game asset: " << (assets / required) << '\n';
            UnloadRenderTexture(target);
            CloseWindow();
            return 1;
        }
    }
    int exitCode = 0;
    try {
        std::filesystem::path savePath = appDirectory / "progress.dat";
#if defined(__APPLE__)
        if (const char *userHome = std::getenv("HOME"))
            savePath =
                std::filesystem::path(userHome) / "Library/Application Support/Slingshot Valley/progress.dat";
#elif defined(_WIN32)
        if (const char *appData = std::getenv("APPDATA"))
            savePath = std::filesystem::path(appData) / "Slingshot Valley/progress.dat";
#else
        if (const char *dataHome = std::getenv("XDG_DATA_HOME"))
            savePath = std::filesystem::path(dataHome) / "slingshot-valley/progress.dat";
        else if (const char *userHome = std::getenv("HOME"))
            savePath = std::filesystem::path(userHome) / ".local/share/slingshot-valley/progress.dat";
#endif
        Application app(assets, savePath, demo);
        if (testUI) {
            BeginTextureMode(target);
            try {
                app.testFlow();
            } catch (const std::exception &error) {
                std::cerr << "UI test failed: " << error.what() << '\n';
                EndTextureMode();
                throw;
            }
            EndTextureMode();
        } else if (!previewDirectory.empty()) {
            std::filesystem::create_directories(previewDirectory);
            for (const auto *name :
                 {"home", "map", "canyon", "night", "game", "pause", "result", "help", "icon"}) {
                BeginTextureMode(target);
                app.renderPreview(name);
                EndTextureMode();
                // Read the renderer's own offscreen texture, never the desktop or other apps.
                auto image = LoadImageFromTexture(target.texture);
                ImageFlipVertical(&image);
                if (std::string(name) == "icon") {
                    auto square = ImageFromImage(image, {280, 0, 720, 720});
                    UnloadImage(image);
                    image = square;
                }
                ExportImage(image, (previewDirectory / (std::string(name) + ".png")).string().c_str());
                UnloadImage(image);
            }
            for (int level = 1; level <= levelCount; level++) {
                const std::string name = TextFormat("level-%02i", level);
                BeginTextureMode(target);
                app.renderPreview(name);
                EndTextureMode();
                auto image = LoadImageFromTexture(target.texture);
                ImageFlipVertical(&image);
                ExportImage(image, (previewDirectory / (name + ".png")).string().c_str());
                UnloadImage(image);
            }
        } else {
            if (startLevel >= 0)
                app.start(startLevel);
            int frames = 0;
            while (!WindowShouldClose() && !app.quitting) {
                float zoom =
                    std::min(GetScreenWidth() / float(screenWidth), GetScreenHeight() / float(screenHeight));
                Vector2 offset{(GetScreenWidth() - screenWidth * zoom) / 2,
                               (GetScreenHeight() - screenHeight * zoom) / 2};
                auto mouse = GetMousePosition();
                mouse = {(mouse.x - offset.x) / zoom, (mouse.y - offset.y) / zoom};
                BeginTextureMode(target);
                app.frame(std::min(GetFrameTime(), .1f), mouse);
                EndTextureMode();
                BeginDrawing();
                ClearBackground(outline);
                DrawTexturePro(target.texture, {0, 0, float(screenWidth), -float(screenHeight)},
                               {offset.x, offset.y, screenWidth * zoom, screenHeight * zoom}, {}, 0, WHITE);
                EndDrawing();
                if (smoke && ++frames >= 120)
                    break;
            }
        }
    } catch (const std::exception &error) {
        std::cerr << "Game error: " << error.what() << '\n';
        exitCode = 1;
    }
    UnloadRenderTexture(target);
    CloseWindow();
    return exitCode;
}
