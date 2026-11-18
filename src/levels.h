#pragma once
#include <array>
#include <vector>
namespace birds {
enum class Kind { Wood, Stone, Glass, Tnt, Platform, Pig, Bird };
enum class BirdType { Red, Dash, Bomb };
struct Placement {
    Kind kind;
    float x, y, width, height;
};
struct Level {
    const char *name;
    const char *hint;
    int theme;
    std::array<BirdType, 3> flock;
    int star2, star3;
    std::vector<Placement> objects;
};
const std::vector<Level> &levels();
} // namespace birds
