#include "levels.h"
namespace birds {
const std::vector<Level> &levels() {
    static const auto campaign = [] {
        std::vector<Level> out;
        const std::array<BirdType, 3> reds{BirdType::Red, BirdType::Red, BirdType::Red};
        const std::array<BirdType, 3> dash{BirdType::Red, BirdType::Dash, BirdType::Red};
        const std::array<BirdType, 3> mixed{BirdType::Red, BirdType::Dash, BirdType::Bomb};
        auto create = [&](const char *name, const char *hint, int theme, auto flock) -> Level & {
            out.push_back({name, hint, theme, flock, 0, 0, {}});
            return out.back();
        };
        auto box = [](Level &l, Kind kind, float x, float y, float w, float h) {
            l.objects.push_back({kind, x, y, w, h});
        };
        auto tower = [&](Level &l, float x, int floors, Kind material = Kind::Wood, float base = 620,
                         float width = 112) {
            for (int f = 0; f < floors; ++f) {
                float bottom = base - f * 102;
                box(l, material, x - width / 2 + 10, bottom - 46, 18, 92);
                box(l, material, x + width / 2 - 10, bottom - 46, 18, 92);
                box(l, Kind::Wood, x, bottom - 97, width + 14, 10);
                box(l, Kind::Pig, x, bottom - 21, 40, 40);
            }
        };
        {
            auto &l = create("First flight", "Pull back. Let go. Make a little chaos.", 0, reds);
            tower(l, 850, 1);
            tower(l, 1010, 1);
        }
        {
            auto &l = create("Double trouble", "Aim low. The whole tower follows.", 0, reds);
            // A broad arch: the long roof carries two exposed pigs.
            box(l, Kind::Wood, 790, 564, 20, 112);
            box(l, Kind::Wood, 1030, 564, 20, 112);
            box(l, Kind::Wood, 910, 500, 270, 16);
            box(l, Kind::Pig, 910, 599, 40, 40);
            box(l, Kind::Pig, 840, 471, 40, 40);
            box(l, Kind::Pig, 980, 471, 40, 40);
        }
        {
            auto &l = create("Glass house", "Glass breaks easily. Dash through it with SPACE.", 0, dash);
            // Narrow glass houses, separated by a freestanding glass stack.
            tower(l, 780, 2, Kind::Glass, 620, 96);
            tower(l, 1080, 1, Kind::Glass, 620, 112);
            box(l, Kind::Glass, 925, 590, 48, 60);
            box(l, Kind::Glass, 925, 540, 48, 40);
            box(l, Kind::Pig, 925, 499, 40, 40);
        }
        {
            auto &l = create("Timber twins", "Two tall towers. One beautiful chain reaction.", 0, dash);
            tower(l, 820, 2);
            tower(l, 1030, 2);
        }
        {
            auto &l = create("Canyon crossing", "Pick your angle. The back tower is waiting.", 1, mixed);
            // Two cliffs force an upward shot; the bridge joins their rooftops.
            box(l, Kind::Platform, 780, 580, 160, 80);
            box(l, Kind::Platform, 1080, 529, 160, 182);
            tower(l, 780, 1, Kind::Glass, 540, 108);
            tower(l, 1080, 1, Kind::Wood, 438, 108);
            box(l, Kind::Wood, 930, 432, 210, 12);
            box(l, Kind::Pig, 930, 405, 40, 40);
            box(l, Kind::Wood, 900, 414, 12, 24);
            box(l, Kind::Wood, 960, 414, 12, 24);
        }
        {
            auto &l = create("Loose cannon", "Red crates pack a punch. Hit the TNT.", 1, mixed);
            // Three explosive cells form a deliberate horizontal chain reaction.
            for (float x : {800.0f, 950.0f, 1100.0f}) {
                box(l, Kind::Tnt, x, 598, 42, 42);
                box(l, Kind::Wood, x - 48, 582, 16, 76);
                box(l, Kind::Wood, x + 48, 582, 16, 76);
                box(l, Kind::Wood, x, 539, 124, 10);
                box(l, Kind::Pig, x, 514, 40, 40);
            }
        }
        {
            auto &l = create("Rock bottom", "Stone is tough. Target the wooden supports.", 1, mixed);
            // Heavy stone roofs balance on breakable wood and glass supports.
            for (float x : {810.0f, 1050.0f}) {
                box(l, Kind::Wood, x - 52, 568, 18, 104);
                box(l, Kind::Glass, x + 52, 568, 18, 104);
                box(l, Kind::Stone, x, 503, 144, 26);
                box(l, Kind::Pig, x, 599, 40, 40);
                box(l, Kind::Pig, x, 469, 40, 40);
            }
        }
        {
            auto &l = create("High stakes", "Higher towers make bigger messes.", 1, mixed);
            // A tall central spire and a smaller outrigger give different trajectories.
            tower(l, 950, 3, Kind::Wood, 620, 100);
            tower(l, 750, 1, Kind::Glass, 620, 100);
            box(l, Kind::Tnt, 1090, 598, 42, 42);
            box(l, Kind::Pig, 1160, 599, 40, 40);
        }
        {
            auto &l = create("After dark", "Bomb has a secret. Press SPACE in flight.", 2, mixed);
            // A staircase of isolated targets climbs toward the moon.
            for (int i = 0; i < 3; i++) {
                float x = 780 + i * 175.0f, height = 40 + i * 65.0f;
                box(l, Kind::Platform, x, 620 - height / 2, 120, height);
                tower(l, x, 1, i == 1 ? Kind::Wood : Kind::Glass, 620 - height, 96);
            }
            box(l, Kind::Tnt, 867, 598, 42, 42);
        }
        {
            auto &l = create("The glass crown", "Break the base. Bring down the crown.", 2, mixed);
            // A pyramid: a wide base, narrow glass crown and exposed top target.
            tower(l, 810, 1, Kind::Wood, 620, 130);
            tower(l, 1050, 1, Kind::Wood, 620, 130);
            box(l, Kind::Wood, 930, 512, 390, 12);
            tower(l, 930, 2, Kind::Glass, 506, 140);
        }
        {
            auto &l = create("Powder keg", "One spark can change everything.", 2, mixed);
            // A fortified arch conceals explosive weak points below the roof.
            box(l, Kind::Stone, 750, 560, 32, 120);
            box(l, Kind::Stone, 1150, 560, 32, 120);
            box(l, Kind::Wood, 950, 490, 435, 20);
            for (float x : {830.0f, 950.0f, 1070.0f}) {
                box(l, Kind::Tnt, x, 598, 42, 42);
                if (x != 950.0f)
                    box(l, Kind::Pig, x, 459, 40, 40);
            }
            tower(l, 950, 1, Kind::Glass, 480, 110);
        }
        {
            auto &l = create("King of the hill", "Your flock. Their fortress. Settle it.", 2, mixed);
            // The final castle combines elevation, heavy roofs and TNT weak points.
            box(l, Kind::Platform, 960, 595, 500, 50);
            tower(l, 790, 1, Kind::Wood, 570, 105);
            tower(l, 1130, 1, Kind::Wood, 570, 105);
            tower(l, 960, 3, Kind::Glass, 570, 110);
            box(l, Kind::Stone, 790, 453, 135, 30);
            box(l, Kind::Stone, 1130, 453, 135, 30);
            box(l, Kind::Tnt, 875, 548, 42, 42);
            box(l, Kind::Tnt, 1045, 548, 42, 42);
        }
        for (auto &l : out) {
            int max = 0;
            for (const auto &p : l.objects)
                max += p.kind == Kind::Pig ? 1000 : p.kind == Kind::Platform ? 0 : 100;
            l.star2 = static_cast<int>(max * .65f);
            l.star3 = static_cast<int>(max * .9f) + 500;
        }
        return out;
    }();
    return campaign;
}
} // namespace birds
