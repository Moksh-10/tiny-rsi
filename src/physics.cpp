#include "physics.hpp"
#include <limits>
namespace ascent {
Contact collide(Vec p, float radius, const Rock& rock) {
 if (rock.points.size() < 3 || radius <= 0) return {};
 float closestSquared = std::numeric_limits<float>::max();
 Vec nearest{}, outward{};
 bool inside = false;
 // Even/odd containment works for both convex ledges and the concave base.
 for (size_t i = 0; i < rock.points.size(); ++i) {
  Vec a = rock.points[i], b = rock.points[(i + 1) % rock.points.size()];
  Vec edge = b - a;
  float edgeSquared = dot(edge, edge);
  if (edgeSquared < 1e-10f) continue;
  if ((a.y > p.y) != (b.y > p.y)) {
   float crossing = a.x + (p.y - a.y) * edge.x / edge.y;
   if (p.x < crossing) inside = !inside;
  }
  float t = std::clamp(dot(p - a, edge) / edgeSquared, 0.f, 1.f);
  Vec q = a + edge * t;
  float squared = dot(p - q, p - q);
  if (squared < closestSquared) {
   closestSquared = squared;
   nearest = q;
   outward = unit({edge.y, -edge.x});
  }
 }
 float distance = std::sqrt(closestSquared);
 if (inside) {
  Vec escape = distance > 1e-6f ? (nearest - p) / distance : outward;
  return {true, escape, nearest, radius + distance};
 }
 if (distance < radius) {
  Vec normal = distance > 1e-6f ? (p - nearest) / distance : outward;
  return {true, normal, nearest, radius - distance};
 }
 return {};
}
static Rock shape(float x,float y,float w,float h,int palette=0){return {{{x-w*.5f,y-h},{x+w*.48f,y-h*.82f},{x+w*.53f,y-h*.2f},{x+w*.30f,y},{x-w*.30f,y+.08f},{x-w*.56f,y-h*.32f}},2.6f,palette};}
std::vector<Rock> makeTerrain(){
 std::vector<Rock> r;
 r.push_back({{{-30,-5},{13,-5},{13,-1.3f},{1,-.4f},{-2,0},{-30,0}},4,0});
 r.push_back(shape(1,1.1f,3.7f,2.2f));r.push_back(shape(3.2f,3.5f,3.1f,3.5f));r.push_back(shape(5,5.8f,2.9f,4));
 r.push_back(shape(5.2f,8.4f,3.7f,3.2f));r.push_back(shape(2.4f,10.8f,3.0f,2.4f));r.push_back(shape(.2f,13.2f,2.4f,3.2f));
 r.push_back(shape(1.8f,15.7f,2.9f,2.6f));r.push_back(shape(4.5f,18.0f,3.0f,3.1f));r.push_back(shape(6.6f,20.5f,2.5f,3.0f));
 r.push_back(shape(5,23,3.2f,2.2f,1));r.push_back(shape(2.2f,25.3f,3.0f,2.7f,1));r.push_back(shape(-.2f,27.6f,2.8f,3.0f,1));
 r.push_back(shape(-2,30,3.4f,3.1f,1));r.push_back(shape(-.5f,32.5f,2.3f,2.8f,1));r.push_back(shape(1.8f,34.7f,3.2f,3.0f,1));
 r.push_back(shape(4.4f,37.1f,2.8f,3.1f,1));r.push_back(shape(5.3f,39.8f,2.6f,3.2f,1));r.push_back(shape(3.3f,42.2f,2.5f,2.7f,1));
 r.push_back(shape(.9f,44.5f,2.7f,3,2));r.push_back(shape(-1.2f,47,2.6f,3,2));r.push_back(shape(-2.3f,49.5f,3.0f,3,2));
 r.push_back(shape(-.1f,52,2.6f,3,2));r.push_back(shape(2.4f,54.5f,2.8f,3,2));r.push_back(shape(4.2f,57,2.7f,3,2));
 r.push_back(shape(2.5f,59.6f,2.6f,3,2));r.push_back(shape(.1f,62.0f,2.8f,3,2));r.push_back(shape(-1.2f,65.2f,3.2f,4,2));
 return r;
}
void Player::reset(){*this=Player{};}
void Player::step(float dt,Vec desired,bool hold,const std::vector<Rock>& terrain){
 if(!std::isfinite(dt)||dt<=0||!std::isfinite(desired.x)||!std::isfinite(desired.y))return;
 if(position.y< -4||std::abs(position.x)>27){int f=falls+1;float b=best,r=runBest,t=elapsed;reset();falls=f;best=b;runBest=r;elapsed=t;return;}
 elapsed+=dt;impact=std::max(0.f,impact-dt*4);aim=limited(desired,3.15f);if(length(aim)<.85f)aim=unit(aim)*.85f;
 Vec old=position;velocity.y-=13.0f*dt;velocity=limited(velocity,19);position+=velocity*dt;
 Vec shoulder=position+Vec{0,.55f};Vec target=shoulder+aim;
 if(!hold)gripping=false;
 // Swept hammer motion prevents tunnelling even at high mouse speed.
 Vec next=tip+limited(target-tip,32*dt);Vec delta=next-tip;int steps=std::max(1,int(length(delta)/.055f)+1);bool contact=false;
 if(!gripping){for(int s=0;s<steps;s++){tip+=delta/float(steps);for(const Rock& r:terrain){auto c=collide(tip,.14f,r);if(c.hit){tip+=c.normal*c.penetration;contact=true;if(hold){gripping=true;anchor=tip;} }}if(gripping)break;}}
 if(gripping){tip=anchor;Vec correction=tip-(position+Vec{0,.55f}+aim);correction=limited(correction,16*dt);position+=correction;}
 else if(contact){Vec correction=tip-(position+Vec{0,.55f}+aim);position+=limited(correction,12*dt);}
 // Rope length is a hard constraint: the head cannot drift away from the hands.
 Vec offset=tip-(position+Vec{0,.55f});if(length(offset)>3.3f){Vec correction=unit(offset)*(length(offset)-3.3f);position+=correction;}
 grounded=false;float speed=length(velocity);
 for(int pass=0;pass<4;pass++)for(const Rock& r:terrain){auto c=collide(position,.55f,r);if(c.hit){position+=c.normal*c.penetration;if(c.normal.y>.45f)grounded=true;float vn=dot(velocity,c.normal);if(vn<0)velocity=velocity-c.normal*vn;if(speed>3)impact=std::max(impact,std::min(1.f,speed/13));}}
 Vec displacement=(position-old)/dt;
 // Preserve launch momentum from a push; keep resting contacts stable.
 velocity=limited(velocity*.35f+displacement*.65f,18.f);velocity.x*=std::exp(-dt*(grounded?7.f:.35f));
 if(gripping)velocity=velocity*.86f;
 if(gripping&&length(tip-(position+Vec{0,.55f}))>3.65f)gripping=false;
 runBest=std::max(runBest,position.y-.55f);
 best=std::max(best,runBest);
 if(position.y< -4||std::abs(position.x)>27){int f=falls+1;float b=best,r=runBest,t=elapsed;reset();falls=f;best=b;runBest=r;elapsed=t;}
}
}
