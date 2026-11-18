#include "world.hpp"
#include "raymath.h"
#include <cmath>
#include <random>
#include <string>
namespace {
std::mt19937 rng(42);float randf(float a,float b){return std::uniform_real_distribution<float>(a,b)(rng);}
Color stone(int p){return p==2?Color{128,145,153,255}:p==1?Color{108,114,113,255}:Color{119,115,99,255};}
Mesh rockMesh(const ascent::Rock&r){
 const int n=int(r.points.size());int tris=n*6-2;Mesh m{};m.vertexCount=tris*3;m.triangleCount=tris;m.vertices=(float*)MemAlloc(m.vertexCount*3*sizeof(float));m.normals=(float*)MemAlloc(m.vertexCount*3*sizeof(float));m.colors=(unsigned char*)MemAlloc(m.vertexCount*4);int k=0;
 auto triangle=[&](Vector3 a,Vector3 b,Vector3 c){Vector3 normal=Vector3Normalize(Vector3CrossProduct(Vector3Subtract(b,a),Vector3Subtract(c,a)));float variation=.83f+.17f*std::abs(std::sin(a.x*13.1f+b.y*7.7f+c.x*2.3f));for(Vector3 p:{a,b,c}){m.vertices[k*3]=p.x;m.vertices[k*3+1]=p.y;m.vertices[k*3+2]=p.z;m.normals[k*3]=normal.x;m.normals[k*3+1]=normal.y;m.normals[k*3+2]=normal.z;for(int q=0;q<3;q++)m.colors[k*4+q]=(unsigned char)(255*variation);m.colors[k*4+3]=255;k++;}};
 auto point=[&](int i,float z){return Vector3{r.points[i].x,r.points[i].y,z};};
 Vector3 center{};for(int i=0;i<n;i++)center=Vector3Add(center,point(i,0));center=Vector3Scale(center,1.f/n);center.z=.58f;
 std::vector<Vector3> ring;for(int i=0;i<n;i++){Vector3 v=Vector3Lerp(center,point(i,0),.57f);v.z=.22f+.35f*std::abs(std::sin(i*2.7f+center.y));ring.push_back(v);}
 for(int i=0;i<n;i++){int j=(i+1)%n;triangle(center,ring[i],ring[j]);triangle(ring[i],point(i,0),point(j,0));triangle(ring[i],point(j,0),ring[j]);}
 for(int i=1;i<n-1;i++)triangle(point(0,-r.depth),point(i+1,-r.depth),point(i,-r.depth));
 for(int i=0;i<n;i++){int j=(i+1)%n;triangle(point(i,0),point(i,-r.depth),point(j,0));triangle(point(j,0),point(i,-r.depth),point(j,-r.depth));}UploadMesh(&m,false);return m;
}
}
World::World(const std::vector<ascent::Rock>& terrain){
 shader=LoadShader(ASCENT_ASSET_DIR "/shaders/world.vs",ASCENT_ASSET_DIR "/shaders/world.fs");
 sphere=LoadModelFromMesh(GenMeshSphere(1,14,20));cylinder=LoadModelFromMesh(GenMeshCylinder(1,1,16));cone=LoadModelFromMesh(GenMeshCone(1,1,10));cube=LoadModelFromMesh(GenMeshCube(1,1,1));
 for(auto*m:{&sphere,&cylinder,&cone,&cube})m->materials[0].shader=shader;
 for(const auto&r:terrain){Model model=LoadModelFromMesh(rockMesh(r));model.materials[0].shader=shader;objects.push_back({model,{0,0,0},stone(r.palette),1});}
 // A distant, independently seeded alpine landscape.
 for(int i=0;i<42;i++){
  float x=randf(-65,65),y=randf(4,13),z=randf(-65,-32);float h=randf(12,20),w=randf(4,10);
  Mesh m=GenMeshCone(1,1,5);Model model=LoadModelFromMesh(m);model.materials[0].shader=shader;model.transform=MatrixScale(w,h,w*.6f);
  objects.push_back({model,{x,y-h,z},i%3==0?Color{145,167,168,255}:Color{104,139,145,255},1});
 }
}
World::~World(){for(auto&o:objects)UnloadModel(o.model);for(auto*m:{&sphere,&cylinder,&cone,&cube})UnloadModel(*m);UnloadShader(shader);}
void World::mesh(Model&m,Vector3 p,Vector3 scale,Color c,Vector3 axis,float angle){DrawModelEx(m,p,axis,angle,scale,c);}
void World::limb(Vector3 a,Vector3 b,float r,Color c){Vector3 d=Vector3Subtract(b,a);Vector3 n=Vector3Normalize(d);Vector3 axis=Vector3CrossProduct({0,1,0},n);float angle=acosf(Clamp(n.y,-1,1))*RAD2DEG;if(Vector3Length(axis)<.001f)axis={1,0,0};mesh(cylinder,a,{r,Vector3Length(d),r},c,axis,angle);}
void World::tree(Vector3 p,float h){
 limb(p,Vector3Add(p,{0,h*.82f,0}),h*.045f,{79,71,53,255});
 for(int i=0;i<4;i++){float f=i/4.f;mesh(cone,Vector3Add(p,{0,h*(.18f+f*.55f),0}),{h*(.34f-f*.22f),h*.55f,h*(.34f-f*.22f)},{static_cast<unsigned char>(43+i*3),static_cast<unsigned char>(76+i*6),static_cast<unsigned char>(65+i*4),255});}
}
void World::draw(Camera3D camera,float time,float altitude){
 float eye[]={camera.position.x,camera.position.y,camera.position.z};SetShaderValue(shader,GetShaderLocation(shader,"eye"),eye,SHADER_UNIFORM_VEC3);SetShaderValue(shader,GetShaderLocation(shader,"time"),&time,SHADER_UNIFORM_FLOAT);
 for(auto&o:objects){Vector3 p=o.position;if(p.z< -10)p.y+=altitude*.72f;DrawModel(o.model,p,o.scale,o.color);}
 // Mossy ledges, gravel, alpine flowers: deterministic placement each frame.
 rng.seed(734);
 auto terrain=ascent::makeTerrain();
 for(size_t i=0;i<terrain.size();i++){
  auto&r=terrain[i];if(i==0)continue;float y=r.points[3].y,x=(r.points[3].x+r.points[4].x)*.5f;
  if(std::abs(y-altitude)>19)continue;
  if(y<42){mesh(sphere,{x,y-.06f,-.8f},{.94f,.12f,1.12f},{78,95,63,255});}
  else mesh(sphere,{x,y-.02f,-.7f},{.96f,.12f,1.1f},{218,226,221,255});
  for(int j=0;j<8;j++){float px=x+randf(-.8,.8),pz=randf(-1.8f,-.1f);mesh(sphere,{px,y+.01f,pz},{randf(.04f,.12f),.06f,.09f},stone(r.palette));}
  if(i%3==1&&y<42)tree({x+.3f,y-.05f,-1.7f},randf(2.2f,3.9f));
  if(i%4==2&&y<40){for(int j=0;j<8;j++){Vector3 a{x+randf(-.7,.7),y,randf(-.9,-.2)};limb(a,Vector3Add(a,{.06f,.23f,0}),.012f,{111,127,70,255});mesh(sphere,Vector3Add(a,{.06f,.24f,0}),{.04f,.04f,.04f},{231,193,112,255});}}
 }
 // Foreground forest and a weathered trail sign at the start.
 tree({-9.1f,0,-1.7f},7.4f);tree({-12,0,-3.2f},5.5f);tree({-16,-.3f,-2},8.1f);tree({9,-.5f,-2},5.7f);
 limb({-2.4f,0,-.7f},{-2.4f,1.8f,-.7f},.07f,{99,75,49,255});mesh(cube,{-2.25f,1.5f,-.65f},{1.3f,.38f,.12f},{132,101,61,255});
 // Distant suspended bridge gives the mountain a human history.
 for(int i=0;i<16;i++){float x=-9+i*.45f,y=15.8f-std::sin(i/15.f*PI)*.7f;mesh(cube,{x,y,-6},{.38f,.10f,1.2f},{104,88,64,255});if(i<15){float nx=x+.45f,ny=15.8f-std::sin((i+1)/15.f*PI)*.7f;limb({x,y+.8f,-5.4f},{nx,ny+.8f,-5.4f},.028f,{107,96,76,255});}}
 // Summit marker and fluttering cloth.
 limb({-1.2f,65.2f,-.5f},{-1.2f,69,-.5f},.045f,{154,145,120,255});
 for(int i=0;i<8;i++){float x=-1.2f+i*.17f;mesh(cube,{x,68.55f+std::sin(time*2+i*.5f)*.04f,-.5f+std::sin(time*2+i*.4f)*.10f},{.18f,.64f,.025f},{224,157,75,255});}
}
void World::player(const ascent::Player&p,float time){
 float x=p.position.x,y=p.position.y;float tilt=std::clamp(-p.velocity.x*1.1f,-12.f,12.f);
 // Copper rim, cast iron belly, feet, torso and articulated arms.
 mesh(sphere,{x,y,.31f},{.57f,.49f,.46f},{39,48,48,255},{0,0,1},tilt);
 mesh(cylinder,{x,y+.20f,.31f},{.56f,.13f,.47f},{75,83,76,255});mesh(cylinder,{x,y+.31f,.31f},{.59f,.065f,.49f},{170,127,75,255});
 mesh(sphere,{x,y+.68f,.28f},{.30f,.48f,.22f},{190,139,101,255});mesh(sphere,{x,y+1.25f,.30f},{.21f,.26f,.20f},{207,159,119,255});
 mesh(sphere,{x-.025f,y+1.40f,.29f},{.21f,.13f,.205f},{55,49,40,255});mesh(sphere,{x+.08f,y+1.15f,.445f},{.11f,.12f,.06f},{78,60,45,255});
 Vector3 shoulder{x,y+.93f,.47f},tip{p.tip.x,p.tip.y,.52f};Vector3 direction=Vector3Normalize(Vector3Subtract(tip,shoulder));Vector3 hand=Vector3Add(shoulder,Vector3Scale(direction,.62f));
 Vector3 elbow{x-.25f+direction.x*.22f,y+.57f+direction.y*.25f,.58f};limb({x-.21f,y+.91f,.37f},elbow,.10f,{181,126,90,255});limb(elbow,hand,.085f,{211,158,112,255});
 Vector3 elbow2{x+.28f+direction.x*.15f,y+.68f+direction.y*.18f,.67f};limb({x+.22f,y+.90f,.43f},elbow2,.105f,{205,151,109,255});limb(elbow2,Vector3Add(hand,Vector3Scale(direction,.16f)),.082f,{214,162,117,255});
 limb(Vector3Subtract(hand,Vector3Scale(direction,.33f)),tip,.045f,{171,114,56,255});
 Vector3 side{-direction.y*.28f,direction.x*.28f,0};limb(Vector3Subtract(tip,side),Vector3Add(tip,side),.12f,{115,128,128,255});
 mesh(sphere,hand,{.105f,.1f,.1f},{218,170,125,255});
 if(p.gripping){float pulse=.025f*std::sin(time*8);DrawSphereWires(tip,.19f+pulse,6,10,{231,187,101,180});}
}
