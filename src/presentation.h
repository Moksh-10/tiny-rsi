#pragma once
#include "simulation.h"
#include <raylib.h>
#include <array>
#include <filesystem>
#include <vector>
namespace birds {
constexpr int screenWidth = 1280, screenHeight = 720;
constexpr Color outline{49, 34, 37, 255}, paper{255, 247, 221, 255}, gold{255, 204, 58, 255};
class Art {
public:
    explicit Art(const std::filesystem::path& assets);
    ~Art();
    Art(const Art&) = delete;
    Art& operator=(const Art&) = delete;
    void background(int theme, float time, bool menu = false) const;
    void label(const char* value, float x, float y, float size, Color color = paper, bool display = false, bool centered = false) const;
    void title(const char* value, float x, float y, float size, Color color = paper, bool centered = false) const;
    void bird(Vector2 p, float radius, BirdType type, float rotation = 0, bool action = false) const;
    void pig(Vector2 p, float radius, float rotation = 0, bool hurt = false) const;
    void block(const Simulation& game, const Entity& e) const;
    void preview(const Level& level, Rectangle area) const;
    bool button(Rectangle rect, const char* caption, Vector2 mouse, bool click, Color fill, bool enabled = true, bool display = true) const;
    bool iconButton(Vector2 center, int icon, Vector2 mouse, bool click, bool active = false) const;
    void stars(Vector2 center, int earned, float radius, float gap = 0) const;
    void panel(Rectangle rect) const;
    void star(Vector2 center, float radius, bool filled) const;
private:
    std::array<Texture2D, 3> scenery{};
    std::array<Texture2D, 8> characters{};
    Font heading{}, body{};
};
struct Particle { Vector2 p, velocity; float life, maxLife, radius; Color color; bool square; };
struct Popup { Vector2 p; int score; float life; };
class Effects {
public:
    void update(float dt);
    void consume(const std::vector<Feedback>& feedback);
    void confetti();
    void draw(const Art& art) const;
    void clear();
    float shake{};
private:
    std::vector<Particle> particles;
    std::vector<Popup> popups;
};
enum class Cue { Click, Launch, Hit, Pop, Boom, Win, Lose, Ability };
class Audio {
public:
    Audio();
    ~Audio();
    void play(Cue cue, bool muted);
    void update(int theme, bool muted);
private:
    bool ready{};
    std::array<Sound, 8> sounds{};
    std::array<Sound, 3> music{};
    int playingTheme{-1};
};
}
