#pragma once
#include "raylib.h"
#include "physics.hpp"
#include <vector>
struct Scenery { Model model{}; Vector3 position{}; Color color{}; float scale=1; };
class World {
public:
 Shader shader{}; std::vector<Scenery> objects; Model sphere{},cylinder{},cone{},cube{}; Material material{};
 explicit World(const std::vector<ascent::Rock>& terrain);
 ~World();
 void draw(Camera3D camera,float time,float altitude);
 void player(const ascent::Player& p,float time);
 void mesh(Model& m,Vector3 pos,Vector3 scale,Color color,Vector3 axis={0,1,0},float angle=0);
 void limb(Vector3 a,Vector3 b,float r,Color color);
private:
 void tree(Vector3 p,float height);
};
