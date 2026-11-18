#pragma once
#include <vector>
#include <cmath>
#include <algorithm>
namespace ascent {
struct Vec { float x=0,y=0; Vec operator+(Vec b)const{return {x+b.x,y+b.y};} Vec operator-(Vec b)const{return {x-b.x,y-b.y};} Vec operator*(float s)const{return {x*s,y*s};} Vec operator/(float s)const{return {x/s,y/s};} Vec& operator+=(Vec b){x+=b.x;y+=b.y;return *this;} };
inline float dot(Vec a,Vec b){return a.x*b.x+a.y*b.y;}
inline float length(Vec v){return std::sqrt(dot(v,v));}
inline Vec unit(Vec v){float l=length(v);return l>0.00001f?v/l:Vec{0,1};}
inline Vec limited(Vec v,float n){float l=length(v);return l>n?v*(n/l):v;}
struct Rock { std::vector<Vec> points; float depth=2; int palette=0; };
struct Contact { bool hit=false; Vec normal{},point{}; float penetration=0; };
Contact collide(Vec p,float radius,const Rock& rock);
std::vector<Rock> makeTerrain();
struct Player {
 Vec position{-5,0.65f},velocity{},tip{-3,1.8f},aim{2,1.2f},anchor{};
 bool gripping=false,grounded=false; float best=0,elapsed=0; int falls=0; float impact=0;
 void reset();
 void step(float dt,Vec desired,bool hold,const std::vector<Rock>& terrain);
};
constexpr float summitHeight=66;
}
