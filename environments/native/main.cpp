#include "simulation.h"
#include "physics.hpp"
#include <nlohmann/json.hpp>
#include <cmath>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
using json = nlohmann::json;
namespace {
constexpr int maxTicks = 18000;
const char* kinds[] = {"wood","stone","glass","tnt","platform","pig","bird"};
const char* birdNames[] = {"red","dash","bomb"};
const char* phases[] = {"aiming","flying","won","lost"};
json vec(float x,float y) { return json::array({x,y}); }
float number(const json& j,const char* key,float low,float high) {
    if(!j.contains(key)||!j[key].is_number()) throw std::invalid_argument(std::string("numeric field required: ")+key);
    double n=j[key].get<double>();
    if(!std::isfinite(n)||n<low||n>high) throw std::invalid_argument(std::string("out of range: ")+key);
    return static_cast<float>(n);
}
int integer(const json& j,const char* key,int low,int high) {
    number(j,key,static_cast<float>(low),static_cast<float>(high));
    double n=j[key].get<double>();
    if(std::floor(n)!=n) throw std::invalid_argument(std::string("integer required: ")+key);
    return static_cast<int>(n);
}
void fields(const json& j,std::initializer_list<const char*> allowed) {
    if(!j.is_object()) throw std::invalid_argument("object required");
    for(auto it=j.begin();it!=j.end();++it) {
        bool found=false; for(auto key:allowed) if(it.key()==key) found=true;
        if(!found) throw std::invalid_argument("unknown field: "+it.key());
    }
}
class Environment {
    std::unique_ptr<birds::Simulation> birds;
    ascent::Player player;
    std::vector<ascent::Rock> terrain=ascent::makeTerrain();
    std::string game;
    int ticks=0;
    bool terminated=false;
    double value() const {
        return birds ? birds->score()/1000.0 : player.runBest/ascent::summitHeight;
    }
    bool done() const {return terminated||ticks>=maxTicks;}
    json result(double reward=0) const {
        json obs;
        if(birds) {
            json entities=json::array();
            int id=0;
            for(const auto& e:birds->entities()) {
                if(e.alive) {
                    auto p=birds->position(e); auto v=b2Body_GetLinearVelocity(e.body);
                    entities.push_back({{"id",id},{"kind",kinds[static_cast<int>(e.kind)]},{"position",vec(p.x,p.y)},
                        {"velocity",vec(v.x*birds::scale,-v.y*birds::scale)},{"angle",birds->angle(e)},
                        {"size",vec(e.width,e.height)},{"health",e.health}});
                }
                ++id;
            }
            obs={{"phase",phases[static_cast<int>(birds->phase())]},{"score",birds->score()},
                 {"pigs_left",birds->pigsLeft()},{"birds_left",birds->birdsLeft()},
                 {"next_bird",birdNames[static_cast<int>(birds->nextBird())]},
                 {"ability_ready",birds->abilityReady()},{"entities",entities}};
        } else {
            json nearby=json::array();
            for(const auto& rock:terrain) {
                bool visible=false;
                for(const auto& p:rock.points) if(std::abs(p.y-player.position.y)<7) visible=true;
                if(visible) { json points=json::array(); for(auto p:rock.points) points.push_back(vec(p.x,p.y)); nearby.push_back(points); }
            }
            obs={{"position",vec(player.position.x,player.position.y)},{"velocity",vec(player.velocity.x,player.velocity.y)},
                 {"tip",vec(player.tip.x,player.tip.y)},{"aim",vec(player.aim.x,player.aim.y)},
                 {"gripping",player.gripping},{"grounded",player.grounded},{"best_height",player.runBest},
                 {"falls",player.falls},{"nearby_terrain",nearby},{"summit_height",ascent::summitHeight},{"winning_body_height",ascent::victoryBodyHeight}};
        }
        return {{"ok",true},{"protocol",1},{"game",game},{"observation",obs},{"reward",reward},
                {"terminated",terminated},{"truncated",ticks>=maxTicks&&!terminated},
                {"info",{{"ticks",ticks},{"max_ticks",maxTicks},{"track","structured-state"},
                          {"success",terminated&&(birds ? birds->phase()==birds::Phase::Won : true)}}}};
    }
public:
    json request(const json& q) {
        if(!q.is_object()) throw std::invalid_argument("object required");
        auto op=q.at("op").get<std::string>();
        if(op=="describe") {
            fields(q,{"op"});
            return {{"ok",true},{"protocol",1},{"games",{"angry-birds","getting-over-it"}},
                    {"tick_hz",60},{"max_ticks",maxTicks},{"max_action_ticks",120},
                    {"angry_birds",{{"levels",birds::levels().size()},{"coordinates","pixels: x right, y down; sling [210,438]; gravity 392 pixels/s^2"},
                     {"actions","launch: x [-95,95], y [-95,95], pull length [8,95]; velocity [-x*10.4,-y*10.4] pixels/s; wait; ability. All require ticks [1,120]."}}},
                    {"getting_over_it",{{"coordinates","meters: x right, y up"},{"actions","hammer: x,y [-3.15,3.15] shoulder-relative aim, hold boolean, ticks [1,120]. Reach clamped to 3.15m."}}}};
        }
        if(op=="reset") {
            fields(q,{"op","game","level"});
            auto next=q.at("game").get<std::string>();
            if(next!="angry-birds"&&next!="getting-over-it") throw std::invalid_argument("unsupported game");
            int level=q.contains("level")?integer(q,"level",0,static_cast<int>(birds::levels().size())-1):0;
            if(next=="getting-over-it"&&level!=0) throw std::invalid_argument("ascent has only level zero");
            if(next=="angry-birds") birds=std::make_unique<birds::Simulation>(level);
            else {birds.reset();player.reset();}
            game=next; ticks=0; terminated=false;
            return result();
        }
        if(game.empty()) throw std::invalid_argument("reset required");
        if(op=="observe") {fields(q,{"op"});return result();}
        if(op!="act") throw std::invalid_argument("unsupported operation");
        fields(q,{"op","action"});
        if(done()) throw std::invalid_argument("episode finished; reset required");
        const auto& a=q.at("action");
        auto type=a.at("type").get<std::string>();
        int count=integer(a,"ticks",1,120);
        float x=0,y=0;bool hold=false;
        if(birds) {
            if(type=="launch") {
                fields(a,{"type","x","y","ticks"});x=number(a,"x",-95,95);y=number(a,"y",-95,95);
                if(std::hypot(x,y)<8||std::hypot(x,y)>95.001f) throw std::invalid_argument("pull length must be [8,95]");
                if(!birds->launch({x,y})) throw std::invalid_argument("launch unavailable");
            } else if(type=="ability") {
                fields(a,{"type","ticks"});
                if(!birds->activateAbility()) throw std::invalid_argument("ability unavailable");
            } else if(type=="wait") fields(a,{"type","ticks"});
            else throw std::invalid_argument("invalid bird action");
        } else {
            if(type!="hammer") throw std::invalid_argument("hammer action required");
            fields(a,{"type","x","y","hold","ticks"});
            x=number(a,"x",-3.15f,3.15f);y=number(a,"y",-3.15f,3.15f);
            if(!a.contains("hold")||!a["hold"].is_boolean()) throw std::invalid_argument("hold boolean required");
            hold=a["hold"].get<bool>();
        }
        // Reward is score/progress difference. Tick cost is explicit and consistent across action sizes.
        double before=value();
        int advanced=0;
        for(int i=0;i<count&&!done();++i) {
            if(birds) {birds->step(1.f/60);terminated=birds->phase()==birds::Phase::Won||birds->phase()==birds::Phase::Lost;}
            else {player.step(1.f/120,{x,y},hold,terrain);player.step(1.f/120,{x,y},hold,terrain);terminated=ascent::reachedSummit(player);}
            ++ticks;++advanced;
        }
        return result(value()-before-advanced*0.00001);
    }
};
}
int main() {
    Environment env;
    // Bounded reader drains oversized records without allocating an unbounded string.
    std::string line;line.reserve(8192);bool oversized=false;char c;
    auto dispatch=[&] {
        try {
            if(oversized) throw std::invalid_argument("request exceeds 65536 bytes");
            std::cout<<env.request(json::parse(line)).dump()<<'\n';
        } catch(const std::exception& e) {std::cout<<json({{"ok",false},{"error",e.what()}}).dump()<<'\n';}
        std::cout.flush();line.clear();oversized=false;
    };
    while(std::cin.get(c)) {if(c=='\n') dispatch();else if(line.size()<65536) line+=c;else oversized=true;}
    if(!line.empty()||oversized) dispatch();
}
