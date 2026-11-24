#version 330
in vec2 fragTexCoord;
in vec4 fragColor;
uniform sampler2D texture0;
uniform vec4 colDiffuse;
out vec4 finalColor;
void main() {
    float distance = texture(texture0, fragTexCoord).a;
    float smoothing = max(fwidth(distance) * 0.65, 0.002);
    float coverage = smoothstep(0.5 - smoothing, 0.5 + smoothing, distance);
    finalColor = vec4(fragColor.rgb * colDiffuse.rgb, coverage * fragColor.a * colDiffuse.a);
}
