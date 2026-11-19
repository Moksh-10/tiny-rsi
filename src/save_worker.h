#pragma once
#include "progress.h"
#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <optional>
#include <thread>
namespace birds {
struct SaveStatus {
    std::uint64_t requested{}, completed{};
    bool failed{};
};
// One I/O owner, one bounded pending snapshot, no references into live gameplay.
class SaveWorker {
  public:
    explicit SaveWorker(std::filesystem::path path);
    ~SaveWorker();
    SaveWorker(const SaveWorker &) = delete;
    SaveWorker &operator=(const SaveWorker &) = delete;
    void submit(Progress snapshot);
    void flush();
    SaveStatus status() const;

  private:
    const std::filesystem::path path;
    mutable std::mutex mutex;
    std::condition_variable changed;
    std::optional<Progress> pending;
    SaveStatus state;
    bool closing{};
    std::jthread worker; // Destroyed/joined before the synchronization primitives.
    void run();
};
} // namespace birds
