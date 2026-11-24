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
namespace {
TextureResource upload(Image image) {
    auto raw = LoadTextureFromImage(image);
    if (!raw.id)
        throw std::runtime_error("Texture upload failed");
    TextureResource texture(raw);
    GenTextureMipmaps(texture.address());
    SetTextureFilter(texture.get(), TEXTURE_FILTER_TRILINEAR);
    return texture;
}
FontResource sdfFont(const std::filesystem::path &path, int baseSize) {
    int bytes{};
    auto file = LoadFileData(path.string().c_str(), &bytes);
    if (!file)
        throw std::runtime_error("Cannot read font: " + path.string());
    Resource<unsigned char *, UnloadFileData> data(file);
    Font raw{};
    raw.baseSize = baseSize;
    raw.glyphCount = 95;
    raw.glyphPadding = 4;
    raw.glyphs = LoadFontData(file, bytes, baseSize, nullptr, 95, FONT_SDF);
    if (!raw.glyphs)
        throw std::runtime_error("Cannot decode font: " + path.string());
    FontResource font(raw);
    ImageResource atlas(GenImageFontAtlas(raw.glyphs, &font.address()->recs, 95, baseSize, 4, 1));
    if (!atlas.get().data)
        throw std::runtime_error("Font atlas allocation failed");
    font.address()->texture = LoadTextureFromImage(atlas.get());
    if (!font.get().texture.id)
        throw std::runtime_error("Font texture allocation failed");
    SetTextureFilter(font.get().texture, TEXTURE_FILTER_BILINEAR);
    for (int i = 0; i < 95; i++) {
        UnloadImage(raw.glyphs[i].image);
        raw.glyphs[i].image.data = nullptr;
    }
    return font;
}
void nineSlice(Texture2D texture, float width, float height) {
    const float sx = texture.width * .047f, sy = texture.height * .047f;
    const float edge = std::min(4.0f, std::min(width, height) * .25f);
    const float sourceX[]{0, sx, texture.width - sx, float(texture.width)};
    const float sourceY[]{0, sy, texture.height - sy, float(texture.height)};
    const float destX[]{-width / 2, -width / 2 + edge, width / 2 - edge, width / 2};
    const float destY[]{-height / 2, -height / 2 + edge, height / 2 - edge, height / 2};
    for (int y = 0; y < 3; y++)
        for (int x = 0; x < 3; x++)
            DrawTexturePro(
                texture, {sourceX[x], sourceY[y], sourceX[x + 1] - sourceX[x], sourceY[y + 1] - sourceY[y]},
                {destX[x], destY[y], destX[x + 1] - destX[x], destY[y + 1] - destY[y]}, {}, 0, WHITE);
}
} // namespace
Art::Art(const std::filesystem::path &assets) {
    owner.check();
    ImageResource atlas(LoadImage((assets / "characters.png").string().c_str()));
    if (!atlas.get().data)
        throw std::runtime_error("Cannot load character atlas");
    const int cellWidth = atlas.get().width / 4, cellHeight = atlas.get().height / 2;
    for (int row = 0; row < 2; row++)
        for (int column = 0; column < 4; column++) {
            ImageResource cell(
                ImageFromImage(atlas.get(), {float(column * cellWidth), float(row * cellHeight),
                                             float(cellWidth), float(cellHeight)}));
            ImageCrop(cell.address(), GetImageAlphaBorder(cell.get(), .08f));
            characters[row * 4 + column] = upload(cell.get());
        }
    atlas.reset();
    ImageResource materialAtlas(LoadImage((assets / "materials.png").string().c_str()));
    if (!materialAtlas.get().data)
        throw std::runtime_error("Cannot load material atlas");
    const int materialWidth = materialAtlas.get().width / 2, materialHeight = materialAtlas.get().height / 2;
    for (int row = 0; row < 2; row++)
        for (int column = 0; column < 2; column++) {
            ImageResource cell(ImageFromImage(materialAtlas.get(),
                                              {float(column * materialWidth), float(row * materialHeight),
                                               float(materialWidth), float(materialHeight)}));
            ImageCrop(cell.address(), GetImageAlphaBorder(cell.get(), .08f));
            materials[row * 2 + column] =
                upload(cell.get()); // Preserve the source detail; no 128px downsampling.
        }
    materialAtlas.reset();
    int i = 0;
    for (const auto *name : {"meadow.png", "canyon.png", "night.png"}) {
        ImageResource image(LoadImage((assets / name).string().c_str()));
        if (!image.get().data)
            throw std::runtime_error("Cannot load scenery");
        scenery[i++] = upload(image.get());
    }
    heading = sdfFont(assets / "Bangers-Regular.ttf", 64);
    body = sdfFont(assets / "Nunito-Bold.ttf", 48);
    auto fontShader = LoadShader(nullptr, (assets / "shaders/sdf.fs").string().c_str());
    if (!fontShader.id || fontShader.id == rlGetShaderIdDefault())
        throw std::runtime_error("SDF shader failed");
    sdfShader = ShaderResource(fontShader);
    auto grade = LoadShader(nullptr, (assets / "shaders/scenery.fs").string().c_str());
    if (!grade.id || grade.id == rlGetShaderIdDefault())
        throw std::runtime_error("Scenery shader failed");
    sceneryShader = ShaderResource(grade);
    themeUniform = GetShaderLocation(grade, "theme");
}
std::size_t Art::textureMemoryBytes() const {
    owner.check();
    std::size_t bytes = textureBytes(heading.get().texture) + textureBytes(body.get().texture);
    for (const auto &t : scenery)
        bytes += textureBytes(t.get());
    for (const auto &t : characters)
        bytes += textureBytes(t.get());
    for (const auto &t : materials)
        bytes += textureBytes(t.get());
    return bytes;
}
void Art::label(const char *value, float x, float y, float size, Color color, bool display,
                bool centered) const {
    owner.check();
    auto font = display ? heading.get() : body.get();
    BeginShaderMode(sdfShader.get());
    float spacing = display ? 1.2f : .25f;
    if (centered)
        x -= MeasureTextEx(font, value, size, spacing).x / 2;
    DrawTextEx(font, value, {x, y}, size, spacing, color);
    EndShaderMode();
}
void Art::title(const char *value, float x, float y, float size, Color color, bool centered) const {
    owner.check();
    BeginShaderMode(sdfShader.get());
    float width = centered ? MeasureTextEx(heading.get(), value, size, 1.2f).x / 2 : 0;
    DrawTextEx(heading.get(), value, {x - width + 3, y + 6}, size, 1.2f, Fade(outline, .4f));
    const float stroke = size < 60 ? 1.0f : 2.0f;
    for (auto d : {Vector2{-stroke, -stroke}, Vector2{stroke, -stroke}, Vector2{-stroke, stroke},
                   Vector2{stroke, stroke}})
        DrawTextEx(heading.get(), value, {x - width + d.x, y + d.y}, size, 1.2f, outline);
    DrawTextEx(heading.get(), value, {x - width, y}, size, 1.2f, color);
    EndShaderMode();
}
void Art::background(int theme, float time, bool menu) const {
    owner.check();
    theme = std::clamp(theme, 0, 2);
    ClearBackground(theme == 2 ? Color{35, 42, 91, 255} : Color{82, 187, 220, 255});
    const auto tex = scenery[theme].get();
    float gradeTheme = static_cast<float>(theme);
    SetShaderValue(sceneryShader.get(), themeUniform, &gradeTheme, SHADER_UNIFORM_FLOAT);
    BeginShaderMode(sceneryShader.get());
    if (tex.id)
        DrawTexturePro(tex, {0, 0, float(tex.width), float(tex.height)}, {0, 0, 1280, 720}, {}, 0, WHITE);
    EndShaderMode();
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
    owner.check();
    const auto texture = characters[(action ? 4 : 0) + column].get();
    const float factors[]{2.55f, 2.85f, 2.4f};
    const Vector2 anchors[]{{.58f, .60f}, {.60f, .66f}, {.53f, .63f}};
    const float width = radius * factors[column], height = width * texture.height / texture.width;
    DrawTexturePro(texture, {0, 0, float(texture.width), float(texture.height)}, {p.x, p.y, width, height},
                   {width * anchors[column].x, height * anchors[column].y}, rotation, WHITE);
}
void Art::pig(Vector2 p, float radius, float rotation, bool hurt) const {
    owner.check();
    const auto texture = characters[hurt ? 7 : 3].get();
    float width = radius * 2.2f, height = width * texture.height / texture.width;
    DrawTexturePro(texture, {0, 0, float(texture.width), float(texture.height)}, {p.x, p.y, width, height},
                   {width * .5f, height * .57f}, rotation, WHITE);
}
void Art::block(const Simulation &game, const Entity &e) const {
    owner.check();
    auto pos = game.renderPosition(e);
    rlPushMatrix();
    rlTranslatef(pos.x, pos.y, 0);
    rlRotatef(game.renderAngle(e) * RAD2DEG, 0, 0, 1);
    const float w = e.width, h = e.height;
    int index = e.kind == Kind::Wood ? 0 : e.kind == Kind::Glass ? 2 : e.kind == Kind::Tnt ? 3 : 1;
    auto texture = materials[index].get();
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
        if (e.kind == Kind::Wood && w > h) {
            rlPushMatrix();
            rlRotatef(90, 0, 0, 1);
            nineSlice(texture, h, w);
            rlPopMatrix();
        } else
            nineSlice(texture, w, h);
    }
    if (e.health < e.maxHealth * .65f) {
        line({-3, -h * .35f}, {4, 0}, 2, outline);
        line({4, 0}, {-3, h * .3f}, 2, outline);
    }
    rlPopMatrix();
}
void Art::shadow(const Simulation &game, const Entity &e) const {
    owner.check();
    if (e.kind == Kind::Platform)
        return;
    auto p = game.renderPosition(e);
    if (e.kind == Kind::Pig || e.kind == Kind::Bird) {
        DrawEllipse(static_cast<int>(p.x + 3), static_cast<int>(p.y + e.height * .44f), e.width * .44f, 3,
                    Fade(outline, .20f));
    } else {
        rlPushMatrix();
        rlTranslatef(p.x + 4, p.y + 5, 0);
        rlRotatef(game.renderAngle(e) * RAD2DEG, 0, 0, 1);
        DrawRectangleRounded({-e.width / 2, -e.height / 2, e.width, e.height}, .12f, 6, Fade(outline, .20f));
        rlPopMatrix();
    }
}
void Art::panel(Rectangle r) const {
    owner.check();
    DrawRectangleRounded({r.x, r.y + 8, r.width, r.height}, .1f, 12, Fade(outline, .3f));
    DrawRectangleRounded({r.x - 3, r.y - 3, r.width + 6, r.height + 6}, .1f, 12, outline);
    DrawRectangleRounded(r, .1f, 12, paper);
    DrawRectangleRoundedLinesEx({r.x + 7, r.y + 7, r.width - 14, r.height - 14}, .1f, 12, 1.5f,
                                {222, 204, 163, 255});
}
bool Art::button(Rectangle r, const char *caption, Vector2 mouse, bool click, Color fill, bool enabled,
                 bool display) const {
    owner.check();
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
    owner.check();
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
    owner.check();
    if (gap == 0)
        gap = radius * 2.55f;
    for (int i = 0; i < 3; i++)
        star({c.x + (i - 1) * gap, c.y + (i == 1 ? -radius * .15f : 0)}, radius, i < earned);
}
bool Art::iconButton(Vector2 p, int icon, Vector2 mouse, bool click, bool active) const {
    owner.check();
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
    owner.check();
    particles.clear();
    popups.clear();
    waves.clear();
    shake = 0;
}
void Effects::update(float dt) {
    owner.check();
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
    for (auto &wave : waves)
        wave.life -= dt;
    waves.erase_if([](const auto &wave) { return wave.life <= 0; });
    particles.erase_if([](auto &p) { return p.life <= 0; });
    popups.erase_if([](auto &p) { return p.life <= 0; });
}
void Effects::consume(std::span<const Feedback> feedback) {
    owner.check();
    for (auto f : feedback) {
        if (f.kind == Kind::Tnt && f.intensity >= 10)
            waves.push_back({{f.position.x, f.position.y}, .45f});
        if (particles.size() == particles.capacity())
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
    owner.check();
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
    owner.check();
    BeginBlendMode(BLEND_ADDITIVE);
    for (auto wave : waves) {
        float radius = (1 - wave.life / .45f) * 165;
        DrawRing(wave.position, std::max(0.0f, radius - 5), radius, 0, 360, 96,
                 Fade(gold, wave.life / .45f * .7f));
    }
    EndBlendMode();
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
    owner.check();
    if (!device.available())
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
        sounds[i] = SoundResource(LoadSoundFromWave(wave));
        SetSoundVolume(sounds[i].get(), i == 2 ? .22f : .45f);
    }
    // Synthesize into one bounded stream instead of preloading three 16-second tracks.
    const int melody[]{0, 7, 12, 7, 4, 9, 7, 4, 0, 4, 7, 12, 9, 7, 4, 2};
    const float roots[]{261.63f, 220.0f, 174.61f};
    for (int theme = 0; theme < 3; theme++)
        for (int note = 0; note < 16; note++)
            notes[theme][note] = roots[theme] * std::pow(2.0f, melody[note] / 12.0f);
    SetAudioStreamBufferSizeDefault(musicFrames);
    auto stream = LoadAudioStream(musicRate, 16, 1);
    if (!IsAudioStreamValid(stream))
        throw std::runtime_error("Music stream allocation failed");
    music = StreamResource(stream);
    SetAudioStreamVolume(stream, .22f);
    PlayAudioStream(stream);
}
void Audio::play(Cue cue, bool muted) {
    owner.check();
    if (device.available() && !muted)
        PlaySound(sounds[static_cast<size_t>(cue)].get());
}
void Audio::update(int theme, bool muted) {
    owner.check();
    if (!device.available())
        return;
    theme = std::clamp(theme, 0, 2);
    SetMasterVolume(muted ? 0.0f : 1.0f);
    if (playingTheme != theme) {
        playingTheme = theme;
        musicCursor = 0;
    }
    if (muted) {
        PauseAudioStream(music.get());
        return;
    }
    if (!IsAudioStreamPlaying(music.get()))
        ResumeAudioStream(music.get());
    const float roots[]{261.63f, 220.0f, 174.61f};
    // At most two blocks can be pending. UpdateAudioStream copies samples before returning.
    for (int block = 0; block < 2 && IsAudioStreamProcessed(music.get()); block++) {
        for (auto &sample : musicSamples) {
            float t = (musicCursor++ % (musicRate * 16)) / float(musicRate), beat = std::fmod(t, .5f);
            float frequency = notes[theme][static_cast<int>(t / .5f) % 16];
            float tone =
                (std::sin(2 * PI * frequency * beat) + .25f * std::sin(2 * PI * frequency * 2 * beat)) *
                std::min(1.0f, beat * 90) * std::exp(-beat * 9);
            float bassBeat = std::fmod(t, 2.0f);
            float bass = std::sin(2 * PI * roots[theme] * .5f * bassBeat) * std::min(1.0f, bassBeat * 10) *
                         std::exp(-bassBeat * 3);
            sample = static_cast<short>((tone * .6f + bass * .3f) * 4200);
        }
        UpdateAudioStream(music.get(), musicSamples.data(), musicFrames);
    }
}
std::size_t Audio::pcmMemoryBytes() const {
    owner.check();
    std::size_t bytes = 0;
    for (const auto &s : sounds) {
        auto v = s.get();
        bytes += static_cast<std::size_t>(v.frameCount) * v.stream.channels * v.stream.sampleSize / 8;
    }
    auto stream = music.get();
    bytes += sizeof(musicSamples) +
             static_cast<std::size_t>(musicFrames) * 2 * stream.channels * stream.sampleSize / 8;
    return bytes;
}
} // namespace birds
