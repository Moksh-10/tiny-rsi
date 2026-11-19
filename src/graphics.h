#pragma once
#include "runtime.h"
#include <atomic>
#include <raylib.h>
#include <thread>
#include <utility>
namespace birds {
// Explicit move-only ownership; borrowed raylib structs never release their handles.
template <class T, void (*Release)(T)> class Resource {
    T value{};
    bool owns{};
    inline static std::atomic_size_t live{};

  public:
    Resource() = default;
    explicit Resource(T handle) : value(handle), owns(true) { ++live; }
    ~Resource() { reset(); }
    Resource(const Resource &) = delete;
    Resource &operator=(const Resource &) = delete;
    Resource(Resource &&other) noexcept : value(other.value), owns(std::exchange(other.owns, false)) {}
    Resource &operator=(Resource &&other) noexcept {
        if (this != &other) {
            reset();
            value = other.value;
            owns = std::exchange(other.owns, false);
        }
        return *this;
    }
    T get() const noexcept { return value; }
    static std::size_t liveCount() noexcept { return live.load(); }
    T *address() noexcept { return &value; }
    void reset() noexcept {
        if (owns) {
            Release(value);
            --live;
            owns = false;
            value = {};
        }
    }
};
using ImageResource = Resource<Image, UnloadImage>;
using TextureResource = Resource<Texture2D, UnloadTexture>;
using FontResource = Resource<Font, UnloadFont>;
using ShaderResource = Resource<Shader, UnloadShader>;
using SoundResource = Resource<Sound, UnloadSound>;
using StreamResource = Resource<AudioStream, UnloadAudioStream>;
using TargetResource = Resource<RenderTexture2D, UnloadRenderTexture>;
class MainThreadOwner {
    const std::thread::id owner = std::this_thread::get_id();

  public:
    void check() const {
        if (std::this_thread::get_id() != owner)
            throw std::logic_error("Graphics/audio accessed from a non-owner thread");
    }
};
class AudioDevice {
    bool ready{};

  public:
    AudioDevice() {
        InitAudioDevice();
        ready = IsAudioDeviceReady();
    }
    ~AudioDevice() {
        if (ready)
            CloseAudioDevice();
    }
    AudioDevice(const AudioDevice &) = delete;
    AudioDevice &operator=(const AudioDevice &) = delete;
    bool available() const { return ready; }
};
class RenderSurface {
    MainThreadOwner owner;
    TargetResource target;
    mutable bool active{};

  public:
    RenderSurface() = default;
    ~RenderSurface() {
        if (active) {
            EndMode2D();
            EndTextureMode();
        }
    }
    RenderSurface(const RenderSurface &) = delete;
    RenderSurface &operator=(const RenderSurface &) = delete;
    void resize(RenderSize size);
    void begin() const;
    void end() const;
    void present() const;
    RenderTexture2D get() const {
        owner.check();
        return target.get();
    }
    RenderSize size() const {
        owner.check();
        return {target.get().texture.width, target.get().texture.height};
    }
};
std::size_t textureBytes(Texture2D texture);
} // namespace birds
