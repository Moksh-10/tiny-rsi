#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <stdexcept>
#include <type_traits>

namespace birds {
// Fixed storage: bursts cannot grow the heap or exceed the declared effects budget.
template <class T, std::size_t Capacity> class FixedPool {
    static_assert(std::is_trivially_copyable_v<T> && Capacity > 0);
    std::array<T, Capacity> storage{};
    std::size_t count{};

  public:
    bool push_back(const T &value) noexcept {
        if (count == Capacity)
            return false;
        storage[count++] = value;
        return true;
    }
    void clear() noexcept { count = 0; }
    std::size_t size() const noexcept { return count; }
    static constexpr std::size_t capacity() noexcept { return Capacity; }
    T *begin() noexcept { return storage.data(); }
    T *end() noexcept { return storage.data() + count; }
    const T *begin() const noexcept { return storage.data(); }
    const T *end() const noexcept { return storage.data() + count; }
    template <class Predicate> void erase_if(Predicate predicate) noexcept {
        std::size_t kept = 0;
        for (std::size_t i = 0; i < count; i++)
            if (!predicate(storage[i]))
                storage[kept++] = storage[i];
        count = kept;
    }
};
struct RenderSize {
    int width{}, height{};
    std::size_t colorBytes() const { return static_cast<std::size_t>(width) * height * 4; }
};
// Physical drawable pixels, independently of logical input coordinates. 4K is the hard GPU budget.
inline RenderSize renderSize(int drawableWidth, int drawableHeight, float overrideScale = 0) {
    if (drawableWidth <= 0 || drawableHeight <= 0 || !std::isfinite(overrideScale) || overrideScale < 0 ||
        overrideScale > 3)
        throw std::invalid_argument("Invalid rendering dimensions or scale");
    float scale =
        overrideScale > 0 ? overrideScale : std::min(drawableWidth / 1280.0f, drawableHeight / 720.0f);
    scale = std::clamp(scale, .25f, 3.0f);
    int height = std::clamp(static_cast<int>(std::floor(720 * scale / 9)) * 9, 180, 2160);
    return {height / 9 * 16, height};
}
} // namespace birds
