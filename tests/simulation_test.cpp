#include "simulation.h"
#include <cmath>
#include <cstdlib>
#include <iostream>

void require(bool condition, const char* message) {
    if (!condition) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
int main() {
    birds::Simulation game;
    require(game.pigsLeft() == 4, "four initial pigs");
    require(!game.launch({0, 0}), "tiny pulls do not consume a bird");
    for (int i = 0; i < 300; ++i) game.step(1.0f / 60);
    require(game.pigsLeft() == 4 && game.score() == 0, "fort remains intact before launch");
    require(game.launch({-85, 25}), "valid launch");
    require(game.birdsLeft() == 2, "launch consumes one bird");
    require(!game.launch({-85, 25}), "cannot launch during flight");
    for (int i = 0; i < 780; ++i) game.step(1.0f / 60);
    require(game.phase() != birds::Phase::Flying, "shot resolves within timeout");
    require(game.score() > 0, "aimed shot hits and damages the fort");
    for (const auto& e : game.entities()) if (e.alive) {
        auto p = game.position(e);
        require(std::isfinite(p.x) && std::isfinite(p.y), "simulation stays finite");
    }
    game.reset();
    require(game.pigsLeft() == 4 && game.birdsLeft() == 3 && game.score() == 0, "reset restores level");
    // Three low shots miss the tower, spend all birds, and reach the lose state.
    for (int shot = 0; shot < 3; ++shot) {
        require(game.launch({-10, 0}), "miss launch accepted");
        for (int i = 0; i < 780; ++i) game.step(1.0f / 60);
    }
    require(game.phase() == birds::Phase::Lost, "exhausted birds produce loss");
    game.reset();
    for (auto pull : {b2Vec2{-85, 5}, b2Vec2{-95, -10}}) {
        if (game.phase() == birds::Phase::Won) break;
        require(game.launch(pull), "aimed launch accepted");
        for (int i = 0; i < 780; ++i) game.step(1.0f / 60);
    }
    require(game.phase() == birds::Phase::Won, "level is winnable within the bird budget");
    const int finalScore = game.score();
    game.step(1.0f);
    require(game.score() == finalScore, "win bonus is awarded only once");
    std::cout << "Simulation checks passed\n";
}
