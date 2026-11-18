#include "progress.h"
#include <algorithm>
#include <fstream>
#include <string>
namespace birds {
bool Progress::unlocked(int level) const {
    return level >= 0 && level < levelCount && (level == 0 || records[level - 1].stars > 0);
}
int Progress::unlockedCount() const {
    int n = 0;
    while (n < levelCount && unlocked(n))
        ++n;
    return n;
}
int Progress::totalStars() const {
    int total = 0;
    for (auto r : records)
        total += r.stars;
    return total;
}
void Progress::complete(int level, int stars, int score) {
    if (!unlocked(level) || stars < 1 || stars > 3 || score < 0)
        return;
    records[level].stars = std::max(records[level].stars, stars);
    records[level].score = std::max(records[level].score, score);
}
bool Progress::load(const std::filesystem::path &path) {
    std::ifstream in(path);
    std::string magic;
    int version{}, mute{};
    Progress candidate;
    if (!(in >> magic >> version >> mute) || magic != "SLINGSHOT_VALLEY" || version != 1 ||
        (mute != 0 && mute != 1))
        return false;
    candidate.muted = mute != 0;
    for (int i = 0; i < levelCount; ++i) {
        auto &r = candidate.records[i];
        if (!(in >> r.stars >> r.score) || r.stars < 0 || r.stars > 3 || r.score < 0 || r.score > 1000000)
            return false;
        if (i > 0 && r.stars > 0 && candidate.records[i - 1].stars == 0)
            return false;
    }
    *this = candidate;
    return true;
}
bool Progress::save(const std::filesystem::path &path) const {
    std::error_code error;
    if (path.has_parent_path())
        std::filesystem::create_directories(path.parent_path(), error);
    if (error)
        return false;
    auto temp = path;
    temp += ".tmp";
    {
        std::ofstream out(temp);
        if (!out)
            return false;
        out << "SLINGSHOT_VALLEY 1 " << muted << '\n';
        for (auto r : records)
            out << r.stars << ' ' << r.score << '\n';
        out.close();
        if (!out)
            return false;
    }
    std::filesystem::rename(temp, path, error);
    return !error;
}
} // namespace birds
