#include "persistence.hpp"
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <limits>
using namespace ascent;
void require(bool value,const char* message){if(!value){std::cerr<<"FAIL: "<<message<<'\n';std::exit(1);}}
int main(){
 auto path=std::filesystem::temp_directory_path()/("ascent-save-test-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()))/"ascent.save";
 Player p;Preferences settings{false,1.3f};p.best=32.4f;p.elapsed=1234;p.falls=6;
 require(writeSave(path,p,settings),"first save creates parent directory");
 Player loaded;Preferences loadedSettings;
 require(readSave(path,loaded,loadedSettings,makeTerrain()),"valid save loads");
 require(loaded.best==p.best&&loaded.elapsed==p.elapsed&&loaded.falls==p.falls&&!loadedSettings.sound&&loadedSettings.sensitivity==1.3f,"save preserves progress and preferences");
 p.best=40;require(writeSave(path,p,settings),"repeated save replaces existing file");require(readSave(path,loaded,loadedSettings,makeTerrain())&&loaded.best==40,"replacement persists newer progress");
 p.position.x=std::numeric_limits<float>::quiet_NaN();require(!writeSave(path,p,settings),"nonfinite state cannot overwrite save");require(readSave(path,loaded,loadedSettings,makeTerrain())&&loaded.best==40,"invalid write preserves previous save");
 auto corrupt=[&](const char* data){std::ofstream f(path);f<<data;};
 corrupt("ASCENT_9\n-5 0.65 10 12 0 1 1");require(!readSave(path,loaded,loadedSettings,makeTerrain()),"unknown versions rejected");
 corrupt("ASCENT_1\n-5 0.65");require(!readSave(path,loaded,loadedSettings,makeTerrain()),"truncated saves rejected");
 corrupt("ASCENT_1\n0 -1 10 12 0 1 1");require(!readSave(path,loaded,loadedSettings,makeTerrain()),"unsafe positions rejected");
 corrupt("ASCENT_1\n-5 0.65 10 12 0 1 99");require(!readSave(path,loaded,loadedSettings,makeTerrain()),"out of range preferences rejected");
 std::filesystem::remove_all(path.parent_path());std::cout<<"All persistence tests passed.\n";
}
