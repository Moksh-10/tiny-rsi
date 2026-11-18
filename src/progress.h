#pragma once
#include <array>
#include <filesystem>
namespace birds {
constexpr int levelCount = 12;
struct Record { int stars{}, score{}; };
class Progress {
public:
    std::array<Record, levelCount> records{};
    bool muted{};
    bool unlocked(int level) const;
    int unlockedCount() const;
    int totalStars() const;
    void complete(int level, int stars, int score);
    bool load(const std::filesystem::path& path);
    bool save(const std::filesystem::path& path) const;
};
}
