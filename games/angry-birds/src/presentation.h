#pragma once
#include "graphics.h"
#include "simulation.h"
#include <array>
#include <cstdint>
#include <filesystem>
#include <raylib.h>
#include <span>
#include <vector>
namespace birds {
constexpr int screenWidth = 1280, screenHeight = 720;
constexpr Color outline{49, 34, 37, 255}, paper{255, 247, 221, 255}, gold{255, 204, 58, 255};
class Art {
  public:
    explicit Art(const std::filesystem::path &assets);
    ~Art() = default;
    std::size_t textureMemoryBytes() const;
    void shadow(const Simulation &game, const Entity &entity) const;
    Art(const Art &) = delete;
    Art &operator=(const Art &) = delete;
    void background(int theme, float time, bool menu = false) const;
    void label(const char *value, float x, float y, float size, Color color = paper, bool display = false,
               bool centered = false) const;
    void title(const char *value, float x, float y, float size, Color color = paper,
               bool centered = false) const;
    void bird(Vector2 p, float radius, BirdType type, float rotation = 0, bool action = false) const;
    void pig(Vector2 p, float radius, float rotation = 0, bool hurt = false) const;
    void block(const Simulation &game, const Entity &e) const;
    bool button(Rectangle rect, const char *caption, Vector2 mouse, bool click, Color fill,
                bool enabled = true, bool display = true) const;
    bool iconButton(Vector2 center, int icon, Vector2 mouse, bool click, bool active = false) const;
    void stars(Vector2 center, int earned, float radius, float gap = 0) const;
    void panel(Rectangle rect) const;
    void star(Vector2 center, float radius, bool filled) const;

  private:
    MainThreadOwner owner;
    std::array<TextureResource, 3> scenery{};
    std::array<TextureResource, 8> characters{};
    std::array<TextureResource, 4> materials{};
    FontResource heading, body;
    ShaderResource sdfShader, sceneryShader;
    int themeUniform{-1};
};
struct Particle {
    Vector2 p, velocity;
    float life, maxLife, radius;
    Color color;
    bool square;
};
struct Popup {
    Vector2 p;
    int score;
    float life;
};
struct Shockwave {
    Vector2 position;
    float life;
};
class Effects {
  public:
    void update(float dt);
    void consume(std::span<const Feedback> feedback);
    void confetti();
    void draw(const Art &art) const;
    void clear();
    float shake{};

  private:
    MainThreadOwner owner;
    FixedPool<Particle, 1024> particles;
    FixedPool<Popup, 128> popups;
    FixedPool<Shockwave, 32> waves;
};
enum class Cue { Click, Launch, Hit, Pop, Boom, Win, Lose, Ability };
class Audio {
  public:
    Audio();
    ~Audio() = default;
    std::size_t pcmMemoryBytes() const;
    void play(Cue cue, bool muted);
    void update(int theme, bool muted);

  private:
    MainThreadOwner owner;
    AudioDevice device;
    std::array<SoundResource, 8> sounds{};
    StreamResource music;
    static constexpr int musicRate = 22050, musicFrames = 2048;
    std::array<short, musicFrames> musicSamples{};
    std::array<std::array<float, 16>, 3> notes{};
    std::uint64_t musicCursor{};
    int playingTheme{-1};
};
} // namespace birds
