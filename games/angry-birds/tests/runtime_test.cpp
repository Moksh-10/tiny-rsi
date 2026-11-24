#include "graphics.h"
#include "runtime.h"
#include "save_worker.h"
#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>
namespace {
void require(bool value, const char *message) {
    if (!value)
        throw std::runtime_error(message);
}
std::atomic<int> released{};
void releaseInt(int value) {
    released += value;
}
using TestResource = birds::Resource<int, releaseInt>;
} // namespace
int main() {
    using namespace birds;
    try {
        const auto path = std::filesystem::temp_directory_path() /
                          ("slingshot-runtime-" +
                           std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directories(path);
        struct Cleanup {
            std::filesystem::path p;
            ~Cleanup() {
                std::error_code ec;
                std::filesystem::remove_all(p, ec);
            }
        } cleanup{path};
        FixedPool<int, 4> pool;
        for (int i = 0; i < 4; i++)
            require(pool.push_back(i), "pool accepts capacity");
        require(!pool.push_back(5) && pool.size() == 4, "pool rejects overflow");
        pool.erase_if([](int n) { return n % 2 == 0; });
        require(pool.size() == 2 && *pool.begin() == 1, "pool compacts live objects");
        pool.clear();
        require(pool.push_back(9), "pool reuses storage");
        require(renderSize(2560, 1440).width == 2560, "Retina physical resolution");
        require(renderSize(7680, 4320).width == 3840, "4K rendering cap");
        require(renderSize(3440, 1440).width == 2560, "ultrawide letterbox preserves aspect");
        require(renderSize(1000, 2000).width <= 1000, "portrait resize remains bounded");
        require(renderSize(1280, 720, 3).colorBytes() == 3840ULL * 2160 * 4,
                "color-only attachment memory budget");
        bool invalid = false;
        try {
            renderSize(0, 720);
        } catch (const std::invalid_argument &) {
            invalid = true;
        }
        require(invalid, "invalid dimensions rejected");
        {
            TestResource a(2);
            TestResource b(std::move(a));
            TestResource c(3);
            c = std::move(b);
        }
        require(released == 5 && TestResource::liveCount() == 0,
                "move ownership releases each resource exactly once");
        try {
            TestResource a(7);
            throw std::runtime_error("injected constructor failure");
        } catch (const std::runtime_error &) {
        }
        require(released == 12 && TestResource::liveCount() == 0, "exception cleanup releases resources");
        MainThreadOwner owner;
        bool rejected = false;
        {
            std::jthread foreign([&] {
                try {
                    owner.check();
                } catch (const std::logic_error &) {
                    rejected = true;
                }
            });
        }
        require(rejected, "wrong-thread graphics access is rejected");
        owner.check();
        const auto destination = path / "player/progress.dat";
        {
            SaveWorker writer(destination);
            std::vector<std::jthread> producers;
            for (int thread = 0; thread < 8; thread++)
                producers.emplace_back([&, thread] {
                    for (int i = 0; i < 100; i++) {
                        Progress snapshot;
                        snapshot.complete(0, 1, thread * 100 + i);
                        writer.submit(snapshot);
                        auto state = writer.status();
                        require(state.completed <= state.requested, "save generations ordered");
                    }
                });
            producers.clear();
            Progress final;
            final.complete(0, 3, 5432);
            final.muted = true;
            writer.submit(final);
            writer.flush();
            auto state = writer.status();
            require(state.completed == 801 && state.requested == 801 && !state.failed,
                    "all producers coalesce to final save");
            Progress loaded;
            require(loaded.load(destination) && loaded.records[0].score == 5432 && loaded.muted,
                    "final snapshot saved intact");
        }
        {
            SaveWorker writer(destination);
            Progress final;
            final.complete(0, 3, 6789);
            writer.submit(final);
        }
        Progress drained;
        require(drained.load(destination) && drained.records[0].score == 6789,
                "shutdown drains pending saves");
        const auto blocker = path / "not-a-directory";
        {
            std::ofstream out(blocker);
            out << "blocked";
        }
        {
            SaveWorker writer(blocker / "progress.dat");
            writer.submit(Progress{});
            writer.flush();
            require(writer.status().failed, "I/O errors reported without deadlock");
        }
        // Independent writers use distinct temporary files; readers see a complete atomic snapshot.
        {
            std::jthread first([&] {
                for (int i = 0; i < 30; i++) {
                    Progress p;
                    p.complete(0, 1, 111);
                    require(p.save(destination), "first atomic writer");
                }
            });
            std::jthread second([&] {
                for (int i = 0; i < 30; i++) {
                    Progress p;
                    p.complete(0, 2, 222);
                    require(p.save(destination), "second atomic writer");
                }
            });
        }
        Progress complete;
        require(complete.load(destination) &&
                    (complete.records[0].score == 111 || complete.records[0].score == 222),
                "concurrent saves never produce partial files");
        std::cout << "Runtime tests passed: fixed pools, DPI budget, resource ownership, thread guards, "
                     "concurrent saves and shutdown\n";
    } catch (const std::exception &error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
