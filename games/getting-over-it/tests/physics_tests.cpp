#include "physics.hpp"
#include <cstdlib>
#include <iostream>
#include <limits>
using namespace ascent;
void require(bool value,const char*message){if(!value){std::cerr<<"FAIL: "<<message<<'\n';std::exit(1);}}
int main(){
 Rock box{{{-2,-2},{2,-2},{2,0},{-2,0}},2,0};
 auto top=collide({0,.3f},.5f,box);require(top.hit&&top.normal.y>.99f&&std::abs(top.penetration-.2f)<.001f,"top surface collision");
 auto inside=collide({0,-.1f},.5f,box);require(inside.hit&&inside.normal.y>.99f&&std::abs(inside.penetration-.6f)<.001f,"embedded bodies eject outward");
 require(!collide({0,1},.5f,box).hit,"separated circles stay separated");
 Rock concave{{{0,0},{4,0},{4,1},{1,1},{1,4},{0,4}},2,0};
 require(collide({.5f,2},.2f,concave).hit,"concave interior is solid");
 require(!collide({2,2},.2f,concave).hit,"concave notch remains open");
 auto notch=collide({1.1f,2},.2f,concave);
 require(notch.hit&&notch.normal.x>.99f,"notch wall pushes outward");
 auto edge=collide({2,0},.2f,box);
 require(edge.hit&&edge.normal.x>.99f,"exact boundary has an outward normal");
 require(!collide({0,0},.5f,Rock{}).hit,"empty geometry has no collision");
 auto terrain=makeTerrain();for(auto&r:terrain){float area=0;for(size_t i=0;i<r.points.size();i++){auto a=r.points[i],b=r.points[(i+1)%r.points.size()];area+=a.x*b.y-b.x*a.y;}require(area>0,"terrain winding must be counterclockwise");}
 Player p;for(int i=0;i<2400;i++)p.step(1.f/120,{2,1},false,terrain);require(std::abs(p.position.y-.55f)<.01f,"player settles on starting ground");require(length(p.velocity)<.1f,"resting body is stable");
 // Plant the hammer below the climber, then extend downward to push upward.
 p.reset();for(int i=0;i<80;i++)p.step(1.f/120,{1,-1.5f},true,terrain);require(p.gripping,"hammer latches onto terrain");float start=p.position.y;for(int i=0;i<35;i++)p.step(1.f/120,{.3f,-2.9f},true,terrain);require(p.position.y>start+.5f,"hammer extension lifts the player");
 p.step(1.f/120,{0,2},false,terrain);require(!p.gripping,"releasing mouse releases anchor");
 p.position={0,-20};p.step(1.f/120,{2,1},false,{});require(p.falls==1&&p.position.y>.5f,"out of bounds recovers safely");
 Player untouched=p;
 p.step(0,{2,1},false,terrain);
 require(p.position.x==untouched.position.x&&p.position.y==untouched.position.y,"zero timestep does not alter simulation");
 p.step(1.f/120,{std::numeric_limits<float>::quiet_NaN(),1},false,terrain);
 require(std::isfinite(p.position.x)&&std::isfinite(p.position.y),"invalid input cannot poison simulation");
 p.reset();p.best=66;
 p.step(1.f/120,{2,1},false,terrain);
 require(p.best==66&&p.runBest<1,"fresh ascent keeps lifetime best without inheriting run progress");
 p.runBest=30;p.position={0,-20};p.tip=p.position+Vec{2,1};p.step(1.f/120,{2,1},false,terrain);
 require(p.best==66&&p.runBest==30,"falls preserve progress within the current ascent");
 p.reset();for(int i=0;i<100000;i++){float t=i*.013f;p.step(1.f/120,{std::sin(t)*3,std::cos(t*1.7f)*3},i%400<260,terrain);require(std::isfinite(p.position.x)&&std::isfinite(p.position.y)&&length(p.velocity)<20,"long simulation stays finite and bounded");}
 std::cout<<"All physics tests passed (100,000-step stress simulation).\n";
}
