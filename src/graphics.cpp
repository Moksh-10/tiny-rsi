#include "graphics.h"
#include <rlgl.h>
namespace birds {
std::size_t textureBytes(Texture2D texture) {
    std::size_t bytes = 0;
    int w = texture.width, h = texture.height;
    for (int i = 0; i < texture.mipmaps; i++) {
        bytes += GetPixelDataSize(w, h, texture.format);
        w = std::max(1, w / 2);
        h = std::max(1, h / 2);
    }
    return bytes;
}
void RenderSurface::resize(RenderSize size) {
    owner.check();
    if (active)
        throw std::logic_error("Cannot resize an active render pass");
    if (size.width <= 0 || size.height <= 0 || size.width > 3840 || size.height > 2160 ||
        size.width * 9 != size.height * 16)
        throw std::invalid_argument("Render target exceeds the graphics budget");
    if (target.get().texture.width == size.width && target.get().texture.height == size.height)
        return;
    // A pure 2D scene has no depth buffer. At 3840x2160 the attachment uses 31.64 MiB.
    RenderTexture2D raw{};
    raw.id = rlLoadFramebuffer();
    if (!raw.id)
        throw std::runtime_error("Unable to allocate render framebuffer");
    TargetResource replacement(raw);
    rlEnableFramebuffer(raw.id);
    raw.texture = {rlLoadTexture(nullptr, size.width, size.height, PIXELFORMAT_UNCOMPRESSED_R8G8B8A8, 1),
                   size.width, size.height, 1, PIXELFORMAT_UNCOMPRESSED_R8G8B8A8};
    *replacement.address() = raw;
    rlFramebufferAttach(raw.id, raw.texture.id, RL_ATTACHMENT_COLOR_CHANNEL0, RL_ATTACHMENT_TEXTURE2D, 0);
    bool complete = raw.texture.id && rlFramebufferComplete(raw.id);
    rlDisableFramebuffer();
    if (!complete)
        throw std::runtime_error("Unable to allocate color render target");
    SetTextureFilter(raw.texture, TEXTURE_FILTER_BILINEAR);
    target = std::move(replacement); // The old target is kept until allocation succeeds.
}
void RenderSurface::begin() const {
    owner.check();
    if (active || !target.get().id)
        throw std::logic_error("Invalid render pass begin");
    active = true;
    BeginTextureMode(target.get());
    Camera2D virtualCamera{};
    virtualCamera.zoom = size().width / 1280.0f;
    BeginMode2D(virtualCamera);
}
void RenderSurface::end() const {
    owner.check();
    if (!active)
        throw std::logic_error("No render pass to end");
    EndMode2D();
    EndTextureMode();
    active = false;
}
void RenderSurface::present() const {
    owner.check();
    if (active)
        throw std::logic_error("Cannot present an active render pass");
    float zoom = std::min(GetScreenWidth() / 1280.0f, GetScreenHeight() / 720.0f);
    Rectangle dest{(GetScreenWidth() - 1280 * zoom) / 2, (GetScreenHeight() - 720 * zoom) / 2, 1280 * zoom,
                   720 * zoom};
    auto tex = target.get().texture;
    DrawTexturePro(tex, {0, 0, float(tex.width), -float(tex.height)}, dest, {}, 0, WHITE);
}
} // namespace birds
