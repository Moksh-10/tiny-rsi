#include "simulation.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>
namespace birds {
Simulation::Simulation(int index) {
    loadLevel(index);
}
Simulation::~Simulation() {
    if (b2World_IsValid(world))
        b2DestroyWorld(world);
}
void Simulation::add(Kind kind, float x, float y, float width, float height, BirdType bird) {
    auto def = b2DefaultBodyDef();
    def.type = kind == Kind::Platform ? b2_staticBody : b2_dynamicBody;
    def.position = {x / scale, (ground - y) / scale};
    def.isBullet = kind == Kind::Bird;
    auto body = b2CreateBody(world, &def);
    auto shape = b2DefaultShapeDef();
    shape.density = kind == Kind::Stone ? 2.5f : kind == Kind::Bird && bird == BirdType::Bomb ? 2.0f : 1.0f;
    shape.material.friction = 0.65f;
    shape.material.restitution = kind == Kind::Bird ? 0.12f : 0.02f;
    shape.enableHitEvents = true;
    if (kind == Kind::Bird || kind == Kind::Pig) {
        b2Circle circle{{0, 0}, width / (2 * scale)};
        b2CreateCircleShape(body, &shape, &circle);
    } else {
        auto box = b2MakeBox(width / (2 * scale), height / (2 * scale));
        b2CreatePolygonShape(body, &shape, &box);
    }
    float hp = kind == Kind::Stone   ? 18.0f
               : kind == Kind::Wood  ? 9.0f
               : kind == Kind::Glass ? 3.0f
               : kind == Kind::Tnt   ? 2.0f
                                     : 4.5f;
    objects.push_back({body, kind, width, height, hp, hp, true, bird});
    objects.back().previous = def.position;
}
void Simulation::loadLevel(int index) {
    if (index < 0 || index >= static_cast<int>(levels().size()))
        throw std::out_of_range("Invalid level");
    level = index;
    reset();
}
void Simulation::reset() {
    if (b2World_IsValid(world))
        b2DestroyWorld(world);
    auto def = b2DefaultWorldDef();
    def.gravity = {0, -9.8f};
    def.hitEventThreshold = 1.0f;
    world = b2CreateWorld(&def);
    objects.clear();
    effects.clear();
    objects.reserve(definition().objects.size() + 3);
    effects.reserve(1024);
    auto floorDef = b2DefaultBodyDef();
    floorDef.position = {16, -0.5f};
    auto floorBody = b2CreateBody(world, &floorDef);
    auto shape = b2DefaultShapeDef();
    shape.material.friction = 0.7f;
    auto floorBox = b2MakeBox(40, 0.5f);
    b2CreatePolygonShape(floorBody, &shape, &floorBox);
    for (const auto &p : definition().objects)
        add(p.kind, p.x, p.y, p.width, p.height);
    state = Phase::Aiming;
    remaining = 3;
    points = 0;
    active = -1;
    abilityUsed = false;
    accumulator = flightTime = quietTime = age = 0;
    // Settle small construction gaps before the player can shoot. No impact damage during warmup.
    for (int i = 0; i < 60; ++i)
        b2World_Step(world, 1.0f / 60, 4);
    for (auto &e : objects) {
        e.previous = b2Body_GetPosition(e.body);
        e.previousAngle = b2Rot_GetAngle(b2Body_GetRotation(e.body));
    }
}
int Simulation::pigsLeft() const {
    return static_cast<int>(std::count_if(objects.begin(), objects.end(),
                                          [](const Entity &e) { return e.alive && e.kind == Kind::Pig; }));
}
int Simulation::stars() const {
    return state != Phase::Won ? 0 : points >= definition().star3 ? 3 : points >= definition().star2 ? 2 : 1;
}
BirdType Simulation::nextBird() const {
    return definition().flock[std::clamp(3 - remaining, 0, 2)];
}
b2Vec2 Simulation::position(const Entity &e) const {
    auto p = b2Body_GetPosition(e.body);
    return {p.x * scale, ground - p.y * scale};
}
float Simulation::angle(const Entity &e) const {
    return -b2Rot_GetAngle(b2Body_GetRotation(e.body));
}
b2Vec2 Simulation::renderPosition(const Entity &e) const {
    const auto current = b2Body_GetPosition(e.body);
    float alpha =
        state == Phase::Won || state == Phase::Lost ? 1.0f : std::clamp(accumulator * 60.0f, 0.0f, 1.0f);
    return {(e.previous.x + (current.x - e.previous.x) * alpha) * scale,
            ground - (e.previous.y + (current.y - e.previous.y) * alpha) * scale};
}
float Simulation::renderAngle(const Entity &e) const {
    float current = b2Rot_GetAngle(b2Body_GetRotation(e.body));
    float delta = std::atan2(std::sin(current - e.previousAngle), std::cos(current - e.previousAngle));
    float alpha =
        state == Phase::Won || state == Phase::Lost ? 1.0f : std::clamp(accumulator * 60.0f, 0.0f, 1.0f);
    return -(e.previousAngle + delta * alpha);
}
bool Simulation::launch(b2Vec2 pull) {
    if (state != Phase::Aiming || remaining <= 0 || !std::isfinite(pull.x) || !std::isfinite(pull.y))
        return false;
    float length = std::hypot(pull.x, pull.y);
    if (length < 8)
        return false;
    if (length > 95) {
        pull.x *= 95 / length;
        pull.y *= 95 / length;
    }
    add(Kind::Bird, sling.x + pull.x, sling.y + pull.y, 38, 38, nextBird());
    active = static_cast<int>(objects.size()) - 1;
    b2Body_SetLinearVelocity(objects.back().body, {-pull.x * 0.26f, pull.y * 0.26f});
    --remaining;
    state = Phase::Flying;
    abilityUsed = false;
    flightTime = quietTime = 0;
    return true;
}
bool Simulation::abilityReady() const {
    return state == Phase::Flying && active >= 0 && objects[active].alive && !abilityUsed &&
           objects[active].bird != BirdType::Red;
}
bool Simulation::activateAbility() {
    if (!abilityReady())
        return false;
    abilityUsed = true;
    auto &e = objects[active];
    if (e.bird == BirdType::Dash) {
        auto v = b2Body_GetLinearVelocity(e.body);
        b2Body_SetLinearVelocity(e.body, {v.x * 1.65f, v.y * .6f});
        effects.push_back({position(e), Kind::Bird, 6, 0});
    } else {
        explode(position(e), 165);
        e.health = 0;
    }
    return true;
}
void Simulation::explode(b2Vec2 center, float radius) {
    effects.push_back({center, Kind::Tnt, 12, 0});
    for (auto &e : objects) {
        if (!e.alive || e.kind == Kind::Platform)
            continue;
        auto p = position(e);
        float dx = p.x - center.x, dy = p.y - center.y;
        float distance = std::hypot(dx, dy);
        if (distance > radius)
            continue;
        float strength = 1 - distance / radius;
        if (e.kind != Kind::Bird)
            e.health -= strength * 26;
        const float inv = 1 / std::max(distance, 15.0f);
        const float impulse = strength * b2Body_GetMass(e.body) * 9;
        b2Body_ApplyLinearImpulseToCenter(e.body, {dx * inv * impulse, -dy * inv * impulse + impulse * .35f},
                                          true);
    }
}
void Simulation::step(float dt) {
    effects.clear();
    if (state == Phase::Won || state == Phase::Lost || !std::isfinite(dt))
        return;
    accumulator += std::clamp(dt, 0.0f, 0.1f);
    while (accumulator >= 1.0f / 60) {
        tick();
        accumulator -= 1.0f / 60;
    }
}
void Simulation::tick() {
    constexpr float dt = 1.0f / 60;
    age += dt;
    for (auto &e : objects)
        if (e.alive) {
            e.previous = b2Body_GetPosition(e.body);
            e.previousAngle = b2Rot_GetAngle(b2Body_GetRotation(e.body));
        }
    b2World_Step(world, dt, 4);
    const auto events = b2World_GetContactEvents(world);
    // Consume transient contact handles before destroying bodies.
    if (age > 0.25f) {
        for (int i = 0; i < events.hitCount; ++i) {
            const auto &hit = events.hitEvents[i];
            if (hit.approachSpeed > 3)
                effects.push_back(
                    {{hit.point.x * scale, ground - hit.point.y * scale}, Kind::Wood, hit.approachSpeed, 0});
            for (auto id : {b2Shape_GetBody(hit.shapeIdA), b2Shape_GetBody(hit.shapeIdB)}) {
                for (auto &e : objects) {
                    if (e.alive && e.kind != Kind::Bird && e.kind != Kind::Platform &&
                        B2_ID_EQUALS(e.body, id)) {
                        e.health -=
                            std::max(0.0f, hit.approachSpeed - 1.5f) * (e.kind == Kind::Pig ? 2.0f : 1.3f);
                    }
                }
            }
        }
    }
    // Detonate all TNT chain reactions before body destruction.
    bool detonated;
    do {
        detonated = false;
        for (auto &e : objects)
            if (e.alive && e.kind == Kind::Tnt && e.health <= 0 && e.health > -1000) {
                e.health = -10000;
                explode(position(e), 165);
                detonated = true;
            }
    } while (detonated);
    bool moving = false;
    for (auto &e : objects) {
        if (!e.alive || e.kind == Kind::Platform)
            continue;
        auto p = position(e);
        auto v = b2Body_GetLinearVelocity(e.body);
        if (std::hypot(v.x, v.y) > 0.4f || std::abs(b2Body_GetAngularVelocity(e.body)) > 0.6f)
            moving = true;
        if (e.health <= 0 || p.x > 1500 || p.x < -200 || p.y > 800) {
            e.alive = false;
            int reward = e.kind == Kind::Pig ? 1000 : e.kind == Kind::Bird ? 0 : 100;
            points += reward;
            effects.push_back({p, e.kind, 6, reward});
            b2DestroyBody(e.body);
        }
    }
    if (pigsLeft() == 0) {
        state = Phase::Won;
        points += remaining * 500;
        return;
    }
    if (state != Phase::Flying)
        return;
    flightTime += dt;
    quietTime = moving ? 0 : quietTime + dt;
    if ((flightTime > 1.5f && quietTime > .8f) || flightTime > 10.0f)
        state = remaining > 0 ? Phase::Aiming : Phase::Lost;
}
} // namespace birds
