#pragma once
#include "levels.h"
#include <box2d/box2d.h>
#include <vector>
namespace birds {
constexpr float scale = 40.0f;
constexpr float ground = 620.0f;
constexpr b2Vec2 sling{210.0f, 438.0f};
enum class Phase { Aiming, Flying, Won, Lost };
struct Entity {
    b2BodyId body{};
    Kind kind{};
    float width{}, height{}, health{}, maxHealth{};
    bool alive{true};
    BirdType bird{BirdType::Red};
};
struct Feedback { b2Vec2 position; Kind kind; float intensity; int points; };
class Simulation {
public:
    explicit Simulation(int level = 0);
    ~Simulation();
    Simulation(const Simulation&) = delete;
    Simulation& operator=(const Simulation&) = delete;
    void reset();
    void loadLevel(int index);
    void step(float dt);
    bool launch(b2Vec2 pull);
    bool activateAbility();
    bool abilityReady() const;
    int pigsLeft() const;
    int stars() const;
    b2Vec2 position(const Entity& entity) const;
    float angle(const Entity& entity) const;
    const std::vector<Entity>& entities() const { return objects; }
    const std::vector<Feedback>& feedback() const { return effects; }
    Phase phase() const { return state; }
    int score() const { return points; }
    int birdsLeft() const { return remaining; }
    int levelIndex() const { return level; }
    const Level& definition() const { return levels()[level]; }
    BirdType nextBird() const;
private:
    b2WorldId world{};
    std::vector<Entity> objects;
    std::vector<Feedback> effects;
    Phase state{Phase::Aiming};
    int level{}, remaining{3}, points{}, active{-1};
    bool abilityUsed{};
    float accumulator{}, flightTime{}, quietTime{}, age{};
    void add(Kind kind, float x, float y, float width, float height, BirdType bird = BirdType::Red);
    void explode(b2Vec2 center, float radius);
    void tick();
};
}
