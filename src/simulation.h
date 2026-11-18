#pragma once
#include <box2d/box2d.h>
#include <vector>

namespace birds {
constexpr float scale = 40.0f;
constexpr float ground = 620.0f;
constexpr b2Vec2 sling{210.0f, 438.0f};
enum class Kind { Wood, Stone, Pig, Bird };
enum class Phase { Aiming, Flying, Won, Lost };
struct Entity {
    b2BodyId body{};
    Kind kind{};
    float width{}, height{}, health{}, maxHealth{};
    bool alive{true};
};
class Simulation {
public:
    Simulation();
    ~Simulation();
    Simulation(const Simulation&) = delete;
    Simulation& operator=(const Simulation&) = delete;
    void reset();
    void step(float dt);
    bool launch(b2Vec2 pull);
    int pigsLeft() const;
    b2Vec2 position(const Entity& entity) const;
    float angle(const Entity& entity) const;
    const std::vector<Entity>& entities() const { return objects; }
    Phase phase() const { return state; }
    int score() const { return points; }
    int birdsLeft() const { return remaining; }
private:
    b2WorldId world{};
    std::vector<Entity> objects;
    Phase state{Phase::Aiming};
    int remaining{3}, points{};
    float accumulator{}, flightTime{}, quietTime{}, age{};
    void add(Kind kind, float x, float y, float width, float height);
    void tick();
};
}
