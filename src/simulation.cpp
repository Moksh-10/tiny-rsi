#include "simulation.h"
#include <algorithm>
#include <cmath>

namespace birds {
Simulation::Simulation() { reset(); }
Simulation::~Simulation() { if (b2World_IsValid(world)) b2DestroyWorld(world); }
void Simulation::add(Kind kind, float x, float y, float width, float height) {
    auto def = b2DefaultBodyDef();
    def.type = b2_dynamicBody;
    def.position = {x / scale, (ground - y) / scale};
    def.isBullet = kind == Kind::Bird;
    auto body = b2CreateBody(world, &def);
    auto shape = b2DefaultShapeDef();
    shape.density = kind == Kind::Stone ? 2.5f : 1.0f;
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
    float hp = kind == Kind::Stone ? 22.0f : kind == Kind::Wood ? 10.0f : 4.5f;
    objects.push_back({body, kind, width, height, hp, hp, true});
}
void Simulation::reset() {
    if (b2World_IsValid(world)) b2DestroyWorld(world);
    auto def = b2DefaultWorldDef();
    def.gravity = {0, -9.8f};
    def.hitEventThreshold = 1.0f;
    world = b2CreateWorld(&def);
    objects.clear();
    auto floorDef = b2DefaultBodyDef();
    floorDef.position = {16, -0.5f};
    auto floorBody = b2CreateBody(world, &floorDef);
    auto shape = b2DefaultShapeDef();
    shape.material.friction = 0.7f;
    auto floorBox = b2MakeBox(40, 0.5f);
    b2CreatePolygonShape(floorBody, &shape, &floorBox);
    for (float x : {830.0f, 1030.0f}) {
        add(Kind::Wood, x - 50, 564, 20, 112);
        add(Kind::Wood, x + 50, 564, 20, 112);
        add(Kind::Wood, x, 499, 140, 18);
        add(Kind::Pig, x, 595, 46, 46);
        add(Kind::Wood, x - 40, 449, 18, 80);
        add(Kind::Wood, x + 40, 449, 18, 80);
        add(Kind::Wood, x, 400, 120, 18);
        add(Kind::Pig, x, 465, 42, 42);
    }
    add(Kind::Stone, 930, 600, 55, 40);
    state = Phase::Aiming;
    remaining = 3;
    points = 0;
    accumulator = flightTime = quietTime = age = 0;
}
int Simulation::pigsLeft() const {
    return static_cast<int>(std::count_if(objects.begin(), objects.end(), [](const Entity& e) {return e.alive && e.kind == Kind::Pig;}));
}
b2Vec2 Simulation::position(const Entity& e) const {
    auto p = b2Body_GetPosition(e.body);
    return {p.x * scale, ground - p.y * scale};
}
float Simulation::angle(const Entity& e) const { return -b2Rot_GetAngle(b2Body_GetRotation(e.body)); }
bool Simulation::launch(b2Vec2 pull) {
    if (state != Phase::Aiming || remaining <= 0) return false;
    float length = std::hypot(pull.x, pull.y);
    if (length < 8) return false;
    if (length > 95) { pull.x *= 95 / length; pull.y *= 95 / length; }
    add(Kind::Bird, sling.x + pull.x, sling.y + pull.y, 38, 38);
    b2Body_SetLinearVelocity(objects.back().body, {-pull.x * 0.26f, pull.y * 0.26f});
    --remaining;
    state = Phase::Flying;
    flightTime = quietTime = 0;
    return true;
}
void Simulation::step(float dt) {
    if (state == Phase::Won || state == Phase::Lost) return;
    accumulator += std::clamp(dt, 0.0f, 0.1f);
    while (accumulator >= 1.0f / 60) { tick(); accumulator -= 1.0f / 60; }
}
void Simulation::tick() {
    constexpr float dt = 1.0f / 60;
    age += dt;
    b2World_Step(world, dt, 4);
    const auto events = b2World_GetContactEvents(world);
    // Read all contact handles before destroying anything: events are transient.
    if (age > 0.75f) {
        for (int i = 0; i < events.hitCount; ++i) {
            const auto& hit = events.hitEvents[i];
            for (auto id : {b2Shape_GetBody(hit.shapeIdA), b2Shape_GetBody(hit.shapeIdB)}) {
                for (auto& e : objects) {
                    if (e.alive && e.kind != Kind::Bird && B2_ID_EQUALS(e.body, id)) {
                        e.health -= std::max(0.0f, hit.approachSpeed - 1.5f) * (e.kind == Kind::Pig ? 2.0f : 1.3f);
                    }
                }
            }
        }
    }
    bool moving = false;
    for (auto& e : objects) {
        if (!e.alive) continue;
        auto p = position(e);
        auto v = b2Body_GetLinearVelocity(e.body);
        if (std::hypot(v.x, v.y) > 0.35f || std::abs(b2Body_GetAngularVelocity(e.body)) > 0.5f) moving = true;
        if (e.health <= 0 || p.x > 1450 || p.x < -200 || p.y > 800) {
            e.alive = false;
            points += e.kind == Kind::Pig ? 1000 : e.kind == Kind::Bird ? 0 : 100;
            b2DestroyBody(e.body);
        }
    }
    if (pigsLeft() == 0) { state = Phase::Won; points += remaining * 500; return; }
    if (state != Phase::Flying) return;
    flightTime += dt;
    quietTime = moving ? 0 : quietTime + dt;
    if ((flightTime > 1.5f && quietTime > 1.0f) || flightTime > 12.0f) {
        state = remaining > 0 ? Phase::Aiming : Phase::Lost;
    }
}
}
