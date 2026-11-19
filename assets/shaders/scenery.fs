#version 330
in vec2 fragTexCoord;
in vec4 fragColor;
uniform sampler2D texture0;
uniform vec4 colDiffuse;
uniform float theme;
out vec4 finalColor;
void main() {
    vec4 source = texture(texture0, fragTexCoord) * colDiffuse * fragColor;
    vec3 color = source.rgb;
    float luma = dot(color, vec3(0.2126, 0.7152, 0.0722));
    color = mix(vec3(luma), color, 1.045);
    color = (color - 0.5) * 1.025 + 0.5;
    vec2 light = theme > 1.5 ? vec2(0.86, 0.15) : vec2(0.78, 0.16);
    float glow = exp(-dot(fragTexCoord - light, fragTexCoord - light) * 8.0);
    vec3 lightColor = theme > 1.5 ? vec3(0.04, 0.07, 0.14) : vec3(0.10, 0.055, 0.005);
    color += lightColor * glow * 0.35;
    float edge = smoothstep(0.35, 0.9, length((fragTexCoord - 0.5) * vec2(1.0, 0.8)));
    color *= 1.0 - edge * 0.055;
    finalColor = vec4(clamp(color, 0.0, 1.0), source.a);
}
