#include "progress.h"
#include "simulation.h"
#include <array>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <vector>
void require(bool condition, const char *message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}
void settle(birds::Simulation &game, int frames = 660) {
    for (int i = 0; i < frames; ++i)
        game.step(1.0f / 60);
}
int main() {
    using namespace birds;
    require(levels().size() == levelCount, "campaign has twelve levels");
    const std::array<std::vector<b2Vec2>, 12> solutions{{{{-85, 5}, {-95, -15}},
                                                         {{-95, 0}},
                                                         {{-95, -10}, {-95, -15}},
                                                         {{-65, 20}, {-95, -15}},
                                                         {{-85, 20}, {-95, 25}},
                                                         {{-95, -15}},
                                                         {{-80, 10}, {-95, -10}},
                                                         {{-95, 0}},
                                                         {{-90, 25}},
                                                         {{-95, -5}, {-95, -15}},
                                                         {{-95, -15}},
                                                         {{-95, 20}}}};
    for (int level = 0; level < levelCount; ++level) {
        Simulation game(level);
        const int pigs = game.pigsLeft();
        require(pigs > 0, "level contains targets");
        require(!game.launch({0, 0}), "tiny pull does not consume bird");
        require(!game.launch({std::numeric_limits<float>::quiet_NaN(), 0}), "invalid launch rejected");
        settle(game, 300);
        require(game.pigsLeft() == pigs && game.score() == 0, "fort stable for five seconds before shot");
        for (size_t i = 0; i < game.definition().objects.size(); i++) {
            const auto &planned = game.definition().objects[i];
            const auto actual = game.position(game.entities()[i]);
            if (std::hypot(actual.x - planned.x, actual.y - planned.y) > 8) {
                std::cerr << "Level " << level + 1 << " object " << i << " shifted before launch\n";
                return 1;
            }
        }
        require(game.stars() == 0, "uncleared level has no stars");
        game.reset();
        for (auto pull : solutions[level]) {
            if (game.phase() == Phase::Won)
                break;
            require(game.launch(pull), "solution launch accepted");
            require(!game.launch(pull), "cannot launch second bird during flight");
            settle(game);
            require(game.phase() != Phase::Flying, "shot resolves");
        }
        if (game.phase() != Phase::Won) {
            std::cerr << "Level " << level + 1 << " did not clear\n";
            return 1;
        }
        require(game.pigsLeft() == 0 && game.stars() == 3, "three stars are attainable on every level");
        int finalScore = game.score();
        settle(game, 60);
        require(game.score() == finalScore, "win bonus awarded once");
        for (auto &e : game.entities())
            if (e.alive) {
                auto p = game.position(e);
                require(std::isfinite(p.x) && std::isfinite(p.y), "finite physics positions");
            }
        game.reset();
        require(game.pigsLeft() == pigs && game.score() == 0 && game.birdsLeft() == 3,
                "retry restores selected level");
        std::cout << "Level " << level + 1 << ": stable, winnable, reset passed\n";
    }
    Simulation miss;
    for (int i = 0; i < 3; i++) {
        require(miss.launch({-10, 0}), "miss accepted");
        settle(miss);
    }
    require(miss.phase() == Phase::Lost, "exhausted flock reaches loss");
    require(!miss.launch({-80, 10}), "cannot launch after loss");
    Simulation ability(4);
    require(!ability.activateAbility(), "ability unavailable before flight");
    ability.launch({-10, 0});
    require(!ability.activateAbility(), "red has no ability");
    settle(ability);
    ability.launch({-10, 0});
    require(ability.abilityReady() && ability.activateAbility(), "dash activates in flight");
    require(!ability.activateAbility(), "ability only activates once");
    settle(ability);
    ability.launch({-10, 0});
    require(ability.activateAbility(), "bomb activates");
    settle(ability);
    bool rejected = false;
    try {
        ability.loadLevel(12);
    } catch (const std::out_of_range &) {
        rejected = true;
    }
    require(rejected, "invalid level rejected");
    Progress progress;
    require(progress.unlocked(0) && !progress.unlocked(1) && !progress.unlocked(-1) && !progress.unlocked(12),
            "initial unlock boundaries");
    progress.complete(2, 3, 9000);
    require(progress.records[2].stars == 0, "locked level cannot advance progression");
    progress.complete(0, 3, 4000);
    progress.complete(0, 1, 1000);
    require(progress.records[0].stars == 3 && progress.records[0].score == 4000 && progress.unlocked(1),
            "best score preserved, next level unlocked");
    const auto path = std::filesystem::temp_directory_path() / "slingshot-valley-test-progress.dat";
    progress.muted = true;
    require(progress.save(path), "atomic save");
    Progress loaded;
    require(loaded.load(path) && loaded.records[0].score == 4000 && loaded.muted, "save reload round trip");
    {
        std::ofstream invalid(path);
        invalid << "SLINGSHOT_VALLEY 1 0\n9 4000\n";
    }
    require(!loaded.load(path) && loaded.records[0].score == 4000,
            "corrupt save rejected without losing in-memory state");
    std::filesystem::remove(path);
    for (int i = 1; i < levelCount; ++i)
        progress.complete(i, 3, 10000);
    require(progress.unlockedCount() == 12 && progress.totalStars() == 36, "complete campaign progression");
    Simulation sixty, thirty, oneTwenty;
    sixty.launch({-85, 5});
    thirty.launch({-85, 5});
    oneTwenty.launch({-85, 5});
    for (int i = 0; i < 120; i++)
        sixty.step(1.0f / 60);
    for (int i = 0; i < 60; i++)
        thirty.step(1.0f / 30);
    for (int i = 0; i < 240; i++)
        oneTwenty.step(1.0f / 120);
    for (size_t i = 0; i < sixty.entities().size(); i++) {
        const auto &a = sixty.entities()[i];
        const auto &b = thirty.entities()[i];
        const auto &c = oneTwenty.entities()[i];
        require(a.alive == b.alive && a.alive == c.alive, "object survival is independent of rendering rate");
        if (a.alive) {
            auto pa = sixty.position(a), pb = thirty.position(b), pc = oneTwenty.position(c);
            require(std::hypot(pa.x - pb.x, pa.y - pb.y) < .01f &&
                        std::hypot(pa.x - pc.x, pa.y - pc.y) < .01f,
                    "physics matches at 30, 60 and 120 FPS");
        }
    }
    std::cout << "Launch rules, abilities, loss state and save integrity passed\n";
}
