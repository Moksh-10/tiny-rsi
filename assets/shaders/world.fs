#version 330
in vec3 position;
in vec3 normal;
in vec4 color;
uniform vec4 colDiffuse;
uniform vec3 eye;
uniform mat4 lightVP;
uniform sampler2D shadowMap;
uniform int shadowsEnabled;
out vec4 finalColor;

float hash(vec3 p) {
    return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453);
}

float visibility(vec3 n, vec3 light) {
    if (shadowsEnabled == 0) return 1.0;
    vec4 projected = lightVP * vec4(position, 1.0);
    vec3 uv = projected.xyz / projected.w * 0.5 + 0.5;
    if (any(lessThan(uv, vec3(0.0))) || any(greaterThan(uv, vec3(1.0)))) return 1.0;
    float bias = max(0.00065 * (1.0 - dot(n, light)), 0.00018);
    vec2 texel = 1.0 / vec2(textureSize(shadowMap, 0));
    float occlusion = 0.0;
    for (int x = -1; x <= 1; ++x) {
        for (int y = -1; y <= 1; ++y) {
            float depth = texture(shadowMap, uv.xy + vec2(x,y) * texel).r;
            occlusion += uv.z - bias > depth ? 1.0 : 0.0;
        }
    }
    // Shadows reduce direct sun; skylight remains, keeping the route readable.
    return 1.0 - occlusion / 9.0;
}

void main() {
    vec3 n = normalize(normal);
    vec3 light = normalize(vec3(-0.65, 0.95, 1.3));
    float sun = max(dot(n, light), 0.0) * visibility(n, light);
    float grain = hash(floor(position * 45.0)) * 0.055;
    float strata = sin(position.y * 14.0 + sin(position.x * 2.0) * 2.0) * 0.018;
    vec3 base = colDiffuse.rgb * color.rgb;
    vec3 skylight = mix(vec3(0.25,0.32,0.36), vec3(0.42,0.49,0.49), n.y * 0.5 + 0.5);
    vec3 lit = base * (skylight + vec3(1.12,0.95,0.70) * sun) + (grain + strata) * base;
    vec3 view = normalize(eye - position);
    float rim = pow(1.0 - max(dot(n,view),0.0),3.0) * 0.09;
    lit += vec3(1.0,0.79,0.48) * rim;
    float fog = 1.0 - exp(-max(0.0,length(eye-position)-29.0)*0.014);
    vec3 fogColor = mix(vec3(0.60,0.72,0.72),vec3(0.57,0.66,0.74),clamp((eye.y-40.0)/30.0,0.0,1.0));
    lit = mix(lit,fogColor,fog);
    finalColor = vec4(lit,colDiffuse.a * color.a);
}
