#include "save_worker.h"
#include <stdexcept>
#include <utility>
namespace birds {
SaveWorker::SaveWorker(std::filesystem::path destination)
    : path(std::move(destination)), worker([this] { run(); }) {}
SaveWorker::~SaveWorker() {
    {
        std::lock_guard lock(mutex);
        closing = true;
    }
    changed.notify_all();
    worker.join(); // Drain the last pending snapshot before the game releases its state.
}
void SaveWorker::submit(Progress snapshot) {
    {
        std::lock_guard lock(mutex);
        if (closing)
            throw std::logic_error("Save submitted after shutdown");
        pending = std::move(snapshot);
        ++state.requested;
    }
    changed.notify_all();
}
void SaveWorker::flush() {
    std::unique_lock lock(mutex);
    const auto revision = state.requested;
    changed.wait(lock, [&] { return state.completed >= revision; });
}
SaveStatus SaveWorker::status() const {
    std::lock_guard lock(mutex);
    return state;
}
void SaveWorker::run() {
    for (;;) {
        Progress snapshot;
        std::uint64_t revision;
        {
            std::unique_lock lock(mutex);
            changed.wait(lock, [&] { return closing || pending.has_value(); });
            if (!pending)
                return;
            snapshot = std::move(*pending);
            pending.reset();
            revision = state.requested;
        }
        bool success = false;
        try {
            success = snapshot.save(path);
        } catch (...) {
            success = false;
        }
        {
            std::lock_guard lock(mutex);
            state.completed = revision;
            state.failed = !success;
        }
        changed.notify_all();
    }
}
} // namespace birds
