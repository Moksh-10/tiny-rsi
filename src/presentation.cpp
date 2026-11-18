#include "presentation.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <rlgl.h>
#include <stdexcept>
#include <string>
namespace birds {
namespace {
Color shade(Color c, float factor) {
    return {static_cast<unsigned char>(c.r * factor), static_cast<unsigned char>(c.g * factor),
            static_cast<unsigned char>(c.b * factor), c.a};
}
void line(Vector2 a, Vector2 b, float width, Color c) {
    DrawLineEx(a, b, width, c);
}
void triangle(Vector2 a, Vector2 b, Vector2 c, Color color) {
    if ((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x) > 0)
        std::swap(b, c);
    DrawTriangle(a, b, c, color);
}
} // namespace
Art::Art(const std::filesystem::path &assets) {
    auto atlas = LoadImage((assets / "characters.png").string().c_str());
    if (!atlas.data)
        throw std::runtime_error("Character atlas could not be loaded");
    const int cellWidth = atlas.width / 4, cellHeight = atlas.height / 2;
    for (int row = 0; row < 2; row++)
        for (int column = 0; column < 4; column++) {
            auto cell = ImageFromImage(atlas, {float(column * cellWidth), float(row * cellHeight),
                                               float(cellWidth), float(cellHeight)});
            auto bounds = GetImageAlphaBorder(cell, .08f);
            ImageCrop(&cell, bounds);
            characters[row * 4 + column] = LoadTextureFromImage(cell);
            SetTextureFilter(characters[row * 4 + column], TEXTURE_FILTER_BILINEAR);
            UnloadImage(cell);
        }
    UnloadImage(atlas);
    auto materialAtlas = LoadImage((assets / "materials.png").string().c_str());
    if (!materialAtlas.data)
        throw std::runtime_error("Material atlas could not be loaded");
    const int materialWidth = materialAtlas.width / 2, materialHeight = materialAtlas.height / 2;
    for (int row = 0; row < 2; row++)
        for (int column = 0; column < 2; column++) {
            auto cell =
                ImageFromImage(materialAtlas, {float(column * materialWidth), float(row * materialHeight),
                                               float(materialWidth), float(materialHeight)});
            ImageCrop(&cell, GetImageAlphaBorder(cell, .08f));
            ImageResize(&cell, 128, 128);
            materials[row * 2 + column] = LoadTextureFromImage(cell);
            SetTextureFilter(materials[row * 2 + column], TEXTURE_FILTER_BILINEAR);
            UnloadImage(cell);
        }
    UnloadImage(materialAtlas);

    int i = 0;
    for (const auto *name : {"meadow.png", "canyon.png", "night.png"}) {
        auto path = (assets / name).string();
        if (FileExists(path.c_str())) {
            scenery[i] = LoadTexture(path.c_str());
            SetTextureFilter(scenery[i], TEXTURE_FILTER_BILINEAR);
        }
        ++i;
    }
    heading = LoadFontEx((assets / "Bangers-Regular.ttf").string().c_str(), 160, nullptr, 0);
    body = LoadFontEx((assets / "Nunito-Bold.ttf").string().c_str(), 64, nullptr, 0);
    SetTextureFilter(heading.texture, TEXTURE_FILTER_BILINEAR);
    SetTextureFilter(body.texture, TEXTURE_FILTER_BILINEAR);
}
Art::~Art() {
    for (auto tex : scenery)
        if (tex.id)
            UnloadTexture(tex);
    for (auto tex : characters)
        if (tex.id)
            UnloadTexture(tex);
    for (auto tex : materials)
        if (tex.id)
            UnloadTexture(tex);
    UnloadFont(heading);
    UnloadFont(body);
}
void Art::label(const char *value, float x, float y, float size, Color color, bool display,
                bool centered) const {
    auto font = display ? heading : body;
    float spacing = display ? 1.2f : .25f;
    if (centered)
        x -= MeasureTextEx(font, value, size, spacing).x / 2;
    DrawTextEx(font, value, {x, y}, size, spacing, color);
}
void Art::title(const char *value, float x, float y, float size, Color color, bool centered) const {
    float width = centered ? MeasureTextEx(heading, value, size, 1.2f).x / 2 : 0;
    DrawTextEx(heading, value, {x - width + 3, y + 6}, size, 1.2f, Fade(outline, .4f));
    const float stroke = size < 60 ? 1.0f : 2.0f;
    for (auto d : {Vector2{-stroke, -stroke}, Vector2{stroke, -stroke}, Vector2{-stroke, stroke},
                   Vector2{stroke, stroke}})
        DrawTextEx(heading, value, {x - width + d.x, y + d.y}, size, 1.2f, outline);
    DrawTextEx(heading, value, {x - width, y}, size, 1.2f, color);
}
void Art::background(int theme, float time, bool menu) const {
    theme = std::clamp(theme, 0, 2);
    ClearBackground(theme == 2 ? Color{35, 42, 91, 255} : Color{82, 187, 220, 255});
    const auto tex = scenery[theme].id ? scenery[theme] : scenery[0];
    if (tex.id)
        DrawTexturePro(tex, {0, 0, float(tex.width), float(tex.height)}, {0, 0, 1280, 720}, {}, 0, WHITE);
    // Small moving motes add life without competing with the playfield.
    for (int i = 0; i < 18; ++i) {
        float x = std::fmod(i * 93.7f + time * (4 + i % 3), 1280.0f);
        float y = 180 + std::fmod(i * 39.5f, 400.0f) + std::sin(time + i) * 12;
        DrawCircleV({x, y}, theme == 2 ? 1.6f : 1,
                    Fade(theme == 2 ? gold : WHITE, .3f + .2f * std::sin(time * 2 + i)));
    }
    if (menu)
        DrawRectangleGradientH(0, 0, 700, 720, Fade(Color{13, 57, 57, 255}, .48f), Fade(outline, 0));
}
void Art::bird(Vector2 p, float radius, BirdType type, float rotation, bool action) const {
    const int column = static_cast<int>(type);
    const auto texture = characters[(action ? 4 : 0) + column];
    const float factors[]{2.55f, 2.85f, 2.4f};
    const Vector2 anchors[]{{.58f, .60f}, {.60f, .66f}, {.53f, .63f}};
    const float width = radius * factors[column], height = width * texture.height / texture.width;
    DrawTexturePro(texture, {0, 0, float(texture.width), float(texture.height)}, {p.x, p.y, width, height},
                   {width * anchors[column].x, height * anchors[column].y}, rotation, WHITE);
}
void Art::pig(Vector2 p, float radius, float rotation, bool hurt) const {
    const auto texture = characters[hurt ? 7 : 3];
    float width = radius * 2.2f, height = width * texture.height / texture.width;
    DrawTexturePro(texture, {0, 0, float(texture.width), float(texture.height)}, {p.x, p.y, width, height},
                   {width * .5f, height * .57f}, rotation, WHITE);
}
void Art::block(const Simulation &game, const Entity &e) const {
    auto pos = game.position(e);
    rlPushMatrix();
    rlTranslatef(pos.x, pos.y, 0);
    rlRotatef(game.angle(e) * RAD2DEG, 0, 0, 1);
    const float w = e.width, h = e.height;
    int index = e.kind == Kind::Wood ? 0 : e.kind == Kind::Glass ? 2 : e.kind == Kind::Tnt ? 3 : 1;
    auto texture = materials[index];
    Rectangle source{0, 0, float(texture.width), float(texture.height)};
    if (e.kind == Kind::Platform) {
        // Tile masonry instead of stretching a single rock across a whole cliff.
        for (float x = -w / 2; x < w / 2; x += 64)
            for (float y = -h / 2; y < h / 2; y += 64)
                DrawTexturePro(texture, source,
                               {x, y, std::min(64.0f, w / 2 - x), std::min(64.0f, h / 2 - y)}, {}, 0, WHITE);
    } else if (e.kind == Kind::Tnt) {
        DrawTexturePro(texture, source, {-w / 2, -h * .64f, w, h * 1.14f}, {}, 0, WHITE);
    } else {
        NPatchInfo patch{source, 6, 6, 6, 6, NPATCH_NINE_PATCH};
        if (e.kind == Kind::Wood && w > h) {
            rlPushMatrix();
            rlRotatef(90, 0, 0, 1);
            DrawTextureNPatch(texture, patch, {-h / 2, -w / 2, h, w}, {}, 0, WHITE);
            rlPopMatrix();
        } else
            DrawTextureNPatch(texture, patch, {-w / 2, -h / 2, w, h}, {}, 0, WHITE);
    }
    if (e.health < e.maxHealth * .65f) {
        line({-3, -h * .35f}, {4, 0}, 2, outline);
        line({4, 0}, {-3, h * .3f}, 2, outline);
    }
    rlPopMatrix();
}
void Art::panel(Rectangle r) const {
    DrawRectangleRounded({r.x, r.y + 8, r.width, r.height}, .1f, 12, Fade(outline, .3f));
    DrawRectangleRounded({r.x - 3, r.y - 3, r.width + 6, r.height + 6}, .1f, 12, outline);
    DrawRectangleRounded(r, .1f, 12, paper);
    DrawRectangleRoundedLinesEx({r.x + 7, r.y + 7, r.width - 14, r.height - 14}, .1f, 12, 1.5f,
                                {222, 204, 163, 255});
}
bool Art::button(Rectangle r, const char *caption, Vector2 mouse, bool click, Color fill, bool enabled,
                 bool display) const {
    bool hover = enabled && CheckCollisionPointRec(mouse, r);
    bool held = hover && IsMouseButtonDown(MOUSE_BUTTON_LEFT);
    float y = r.y + (held ? 5 : hover ? -2 : 0);
    DrawRectangleRounded({r.x - 2, r.y + 5, r.width + 4, r.height + 3}, .25f, 12, outline);
    DrawRectangleRounded({r.x, y, r.width, r.height}, .25f, 12,
                         enabled ? shade(fill, hover ? 1.0f : .92f) : Color{158, 161, 147, 255});
    DrawRectangleRoundedLinesEx({r.x + 3, y + 3, r.width - 6, r.height - 6}, .25f, 12, 2, Fade(WHITE, .3f));
    label(caption, r.x + r.width / 2, y + r.height / 2 - (display ? 19 : 12), display ? 36 : 24,
          enabled ? paper : Fade(paper, .7f), display, true);
    return hover && click;
}
void Art::star(Vector2 center, float radius, bool filled) const {
    Vector2 points[10];
    for (int i = 0; i < 10; ++i) {
        float a = (-90 + i * 36) * DEG2RAD;
        float r = (i % 2 ? .46f : 1) * radius;
        points[i] = {center.x + std::cos(a) * r, center.y + std::sin(a) * r};
    }
    Color c = filled ? gold : Color{182, 172, 144, 255};
    for (int i = 0; i < 10; i++) {
        // Raylib triangles are counter-clockwise in screen coordinates.
        triangle(center, points[(i + 1) % 10], points[i], c);
        line(points[i], points[(i + 1) % 10], std::max(1.0f, radius * .08f),
             filled ? Color{174, 117, 31, 255} : Color{143, 135, 116, 255});
    }
    if (filled)
        DrawCircleV({center.x - radius * .15f, center.y - radius * .26f}, radius * .11f, Fade(WHITE, .8f));
}
void Art::stars(Vector2 c, int earned, float radius, float gap) const {
    if (gap == 0)
        gap = radius * 2.55f;
    for (int i = 0; i < 3; i++)
        star({c.x + (i - 1) * gap, c.y + (i == 1 ? -radius * .15f : 0)}, radius, i < earned);
}
bool Art::iconButton(Vector2 p, int icon, Vector2 mouse, bool click, bool active) const {
    bool hover = CheckCollisionPointCircle(mouse, p, 25);
    DrawCircleV({p.x, p.y + 4}, 27, outline);
    DrawCircleV(p, 26, hover ? paper : Color{255, 235, 183, 255});
    DrawCircleLines(static_cast<int>(p.x), static_cast<int>(p.y), 24, {207, 167, 92, 255});
    Color c = outline;
    if (icon == 0) {
        DrawRectangleRec({p.x - 8, p.y - 10, 5, 20}, c);
        DrawRectangleRec({p.x + 3, p.y - 10, 5, 20}, c);
    }
    if (icon == 1) {
        DrawRing(p, 9, 12, 45, 325, 24, c);
        triangle({p.x + 11, p.y - 13}, {p.x + 2, p.y - 12}, {p.x + 11, p.y - 4}, c);
    }
    if (icon == 2) {
        triangle({p.x, p.y - 12}, {p.x - 13, p.y}, {p.x + 13, p.y}, c);
        DrawRectangleRec({p.x - 9, p.y - 1, 18, 13}, c);
        DrawRectangleRec({p.x - 3, p.y + 4, 6, 8}, paper);
    }
    if (icon == 3) {
        triangle({p.x + 10, p.y - 12}, {p.x - 10, p.y}, {p.x + 10, p.y + 12}, c);
    }
    if (icon == 4) {
        DrawRectangleRec({p.x - 12, p.y - 5, 7, 10}, c);
        triangle({p.x + 1, p.y - 11}, {p.x - 8, p.y}, {p.x + 1, p.y + 11}, c);
        if (active) {
            line({p.x + 5, p.y - 8}, {p.x + 15, p.y + 8}, 3, c);
            line({p.x + 15, p.y - 8}, {p.x + 5, p.y + 8}, 3, c);
        } else
            DrawRing({p.x + 1, p.y}, 8, 10, -65, 65, 12, c);
    }
    if (icon == 5) {
        for (int i = 0; i < 4; i++)
            DrawRectangleRec({p.x - 10 + float(i % 2) * 12, p.y - 10 + float(i / 2) * 12, 8, 8}, c);
    }
    if (icon == 6) {
        label("?", p.x, p.y - 17, 33, c, true, true);
    }
    return hover && click;
}
void Effects::clear() {
    particles.clear();
    popups.clear();
    shake = 0;
}
void Effects::update(float dt) {
    shake = std::max(0.0f, shake - dt * 25);
    for (auto &p : particles) {
        p.life -= dt;
        p.velocity.y += 180 * dt;
        p.p.x += p.velocity.x * dt;
        p.p.y += p.velocity.y * dt;
    }
    for (auto &p : popups) {
        p.life -= dt;
        p.p.y -= 35 * dt;
    }
    std::erase_if(particles, [](auto &p) { return p.life <= 0; });
    std::erase_if(popups, [](auto &p) { return p.life <= 0; });
}
void Effects::consume(const std::vector<Feedback> &feedback) {
    for (auto f : feedback) {
        if (particles.size() > 700)
            break;
        Color color = f.kind == Kind::Pig     ? Color{144, 207, 63, 255}
                      : f.kind == Kind::Glass ? Color{156, 240, 255, 255}
                      : f.kind == Kind::Tnt   ? Color{255, 179, 48, 255}
                                              : Color{221, 167, 94, 255};
        int count = f.kind == Kind::Tnt ? 45 : f.points ? 16 : 4;
        for (int i = 0; i < count; i++) {
            float a = GetRandomValue(0, 360) * DEG2RAD;
            float speed = static_cast<float>(GetRandomValue(40, f.kind == Kind::Tnt ? 260 : 150));
            float life = GetRandomValue(30, 80) / 100.0f;
            particles.push_back({{f.position.x, f.position.y},
                                 {std::cos(a) * speed, std::sin(a) * speed},
                                 life,
                                 life,
                                 GetRandomValue(2, 5) * 1.0f,
                                 color,
                                 f.kind != Kind::Pig});
        }
        if (f.points)
            popups.push_back({{f.position.x, f.position.y}, f.points, 1.2f});
        shake = std::max(shake, std::min(7.0f, f.intensity * .4f));
    }
}
void Effects::confetti() {
    for (int i = 0; i < 120; i++) {
        Color c = i % 3 == 0 ? gold : i % 3 == 1 ? Color{236, 76, 65, 255} : Color{103, 195, 185, 255};
        particles.push_back({{GetRandomValue(180, 1100) * 1.0f, GetRandomValue(-500, -30) * 1.0f},
                             {GetRandomValue(-60, 60) * 1.0f, GetRandomValue(20, 130) * 1.0f},
                             4,
                             4,
                             GetRandomValue(3, 6) * 1.0f,
                             c,
                             true});
    }
}
void Effects::draw(const Art &art) const {
    for (auto p : particles) {
        Color c = Fade(p.color, std::min(1.0f, p.life * 3));
        if (p.square)
            DrawRectanglePro({p.p.x, p.p.y, p.radius * 2, p.radius}, {p.radius, p.radius / 2}, p.life * 180,
                             c);
        else
            DrawCircleV(p.p, p.radius, c);
    }
    for (auto p : popups)
        art.title(TextFormat("+%i", p.score), p.p.x, p.p.y, 25, Fade(paper, std::min(1.0f, p.life * 2)),
                  true);
}
Audio::Audio() {
    InitAudioDevice();
    ready = IsAudioDeviceReady();
    if (!ready)
        return;
    constexpr unsigned rate = 22050;
    for (int i = 0; i < 8; i++) {
        float duration = i == 5 ? .65f : i == 4 ? .4f : .16f;
        std::vector<short> samples(static_cast<size_t>(duration * rate));
        const float frequencies[]{600, 420, 120, 720, 65, 523, 160, 880};
        float phase = 0;
        uint32_t noise = 42;
        for (size_t n = 0; n < samples.size(); n++) {
            float t = n / float(rate), env = std::pow(1 - t / duration, 2);
            float freq = frequencies[i];
            if (i == 1)
                freq = 420 - 300 * t / duration;
            if (i == 5)
                freq = n < samples.size() / 3 ? 523 : n < samples.size() * 2 / 3 ? 659 : 784;
            phase += 2 * PI * freq / rate;
            noise = noise * 1664525 + 1013904223;
            float wave = std::sin(phase);
            if (i == 2 || i == 4)
                wave = wave * .4f + (static_cast<int>(noise >> 16) / 32768.0f - 1) * .6f;
            samples[n] = static_cast<short>(wave * env * 7500);
        }
        Wave wave{static_cast<unsigned>(samples.size()), rate, 16, 1, samples.data()};
        sounds[i] = LoadSoundFromWave(wave);
        SetSoundVolume(sounds[i], i == 2 ? .22f : .45f);
    }
    // Original, seamlessly looping marimba/pad cues; no external audio assets.
    const int melody[]{0, 7, 12, 7, 4, 9, 7, 4, 0, 4, 7, 12, 9, 7, 4, 2};
    for (int theme = 0; theme < 3; theme++) {
        constexpr float duration = 16;
        std::vector<short> samples(static_cast<size_t>(duration * rate));
        const float roots[]{261.63f, 220.0f, 174.61f};
        for (size_t n = 0; n < samples.size(); n++) {
            float t = n / float(rate), beat = std::fmod(t, .5f);
            int note = static_cast<int>(t / .5f) % 16;
            float frequency = roots[theme] * std::pow(2.0f, melody[note] / 12.0f);
            float attack = std::min(1.0f, beat * 90), decay = std::exp(-beat * 9);
            float tone =
                (std::sin(2 * PI * frequency * beat) + .25f * std::sin(2 * PI * frequency * 2 * beat)) *
                attack * decay;
            float bassBeat = std::fmod(t, 2.0f);
            float bass = std::sin(2 * PI * roots[theme] * .5f * bassBeat) * std::min(1.0f, bassBeat * 10) *
                         std::exp(-bassBeat * 3);
            samples[n] = static_cast<short>((tone * .6f + bass * .3f) * 4200);
        }
        Wave wave{static_cast<unsigned>(samples.size()), rate, 16, 1, samples.data()};
        music[theme] = LoadSoundFromWave(wave);
        SetSoundVolume(music[theme], .22f);
    }
}
Audio::~Audio() {
    if (ready) {
        for (auto s : sounds)
            UnloadSound(s);
        for (auto s : music)
            UnloadSound(s);
        CloseAudioDevice();
    }
}
void Audio::play(Cue cue, bool muted) {
    if (ready && !muted)
        PlaySound(sounds[static_cast<size_t>(cue)]);
}
void Audio::update(int theme, bool muted) {
    if (!ready)
        return;
    theme = std::clamp(theme, 0, 2);
    SetMasterVolume(muted ? 0.0f : 1.0f);
    if (playingTheme != theme) {
        if (playingTheme >= 0)
            StopSound(music[playingTheme]);
        playingTheme = theme;
    }
    if (!muted && !IsSoundPlaying(music[theme]))
        PlaySound(music[theme]);
}
} // namespace birds
