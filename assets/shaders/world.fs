#version 330
in vec3 position;
in vec3 normal;
in vec4 color;
uniform vec4 colDiffuse;
uniform vec3 eye;
uniform float time;
out vec4 finalColor;
float hash(vec3 p){return fract(sin(dot(p,vec3(127.1,311.7,74.7)))*43758.5453);}
void main(){
 vec3 n=normalize(normal);vec3 light=normalize(vec3(-.65,.95,1.3));float diffuse=max(dot(n,light),0.0);
 float grain=hash(floor(position*45.0))*.055;
 float strata=sin(position.y*14.0+sin(position.x*2.0)*2.0)*.018;
 vec3 base=colDiffuse.rgb*color.rgb;
 vec3 lit=base*(vec3(.34,.43,.47)+vec3(1.12,.95,.70)*diffuse)+(grain+strata)*base;
 vec3 view=normalize(eye-position);float rim=pow(1.0-max(dot(n,view),0.0),3.0)*.09;
 lit+=vec3(1.0,.79,.48)*rim;
 float fog=1.0-exp(-max(0.0,length(eye-position)-29.0)*.014);
 lit=mix(lit,vec3(.60,.72,.72),fog);
 finalColor=vec4(lit,colDiffuse.a*color.a);
}
