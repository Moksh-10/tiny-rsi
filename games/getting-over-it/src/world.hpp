#pragma once
#include "physics.hpp"
#include "raylib.h"
#include <vector>

struct Scenery {
 Model model{};
 Vector3 position{};
 Color color{};
 float scale=1;
};

class World {
public:
 explicit World(const std::vector<ascent::Rock>& terrain);
 ~World();
 World(const World&)=delete;
 World& operator=(const World&)=delete;
 void renderShadows(Camera3D camera,const ascent::Player& player,float time);
 void draw(Camera3D camera,float time,float altitude);
 void player(const ascent::Player& p,float time);
 void mesh(Model& model,Vector3 position,Vector3 scale,Color color,Vector3 axis={0,1,0},float angle=0);
 void limb(Vector3 a,Vector3 b,float radius,Color color);
 bool graphicsReady() const;
private:
 struct Instance {
  Model* model;
  Vector3 position,scale;
  Color color;
  Vector3 axis;
  float angle;
 };
 Shader shader{},depthShader{};
 RenderTexture2D shadowMap{};
 std::vector<Scenery> objects;
 std::vector<Instance> decorations;
 Model sphere{},cylinder{},cone{},cube{};
 int eyeLocation=-1,lightMatrixLocation=-1,shadowSamplerLocation=-1,shadowEnabledLocation=-1;
 bool buildingDecorations=false,shadowPass=false,shadowReady=false;
 void buildDecorations(const std::vector<ascent::Rock>& terrain);
 void tree(Vector3 position,float height);
};
