#include "world.hpp"
#include "resources.hpp"
#include "persistence.hpp"
#include <cstdlib>
#include "raymath.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <random>
#include <string>
#include <vector>

namespace {
constexpr Color ivory{241,237,220,255}, muted{165,184,179,255}, gold{224,179,104,255}, dark{17,33,36,255};
struct Fonts { Font body{},title{}; bool customBody=false,customTitle=false;
 Fonts(){body=GetFontDefault();title=body;
  std::string root=resourceRoot()+"/fonts/";
  std::string sansAsset=root+"Lato.ttf",serifAsset=root+"Lora.ttf";
  const char* sans[]={sansAsset.c_str(),"/System/Library/Fonts/Supplemental/Arial.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","C:/Windows/Fonts/segoeui.ttf"};
  const char* serif[]={serifAsset.c_str(),"/System/Library/Fonts/Supplemental/Georgia.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf","C:/Windows/Fonts/georgia.ttf"};
  for(auto s:sans)if(FileExists(s)){body=LoadFontEx(s,64,nullptr,0);customBody=true;break;}
  for(auto s:serif)if(FileExists(s)){title=LoadFontEx(s,144,nullptr,0);customTitle=true;break;}
  SetTextureFilter(body.texture,TEXTURE_FILTER_BILINEAR);SetTextureFilter(title.texture,TEXTURE_FILTER_BILINEAR);
 }
 ~Fonts(){if(customBody)UnloadFont(body);if(customTitle)UnloadFont(title);}
};
struct UI {
 Fonts& fonts;float sx=1,sy=1;Vector2 mouse{};bool clicked=false,enabled=true,inputEnabled=true;
 void begin(){sx=GetScreenWidth()/1440.f;sy=GetScreenHeight()/900.f;Vector2 m=inputEnabled?GetMousePosition():Vector2{};mouse={m.x/sx,m.y/sy};clicked=inputEnabled&&IsMouseButtonPressed(MOUSE_BUTTON_LEFT);}
 Rectangle rect(float x,float y,float w,float h){return {x*sx,y*sy,w*sx,h*sy};}
 void text(const char*s,float x,float y,float size,Color c=ivory,bool serif=false){DrawTextEx(serif?fonts.title:fonts.body,s,{x*sx,y*sy},size*sy,serif?0:1*sx,c);}
 void line(float x,float y,float w,Color c){DrawLineEx({x*sx,y*sy},{(x+w)*sx,y*sy},sy,c);}
 void panel(float x,float y,float w,float h,Color c={15,32,35,225}){DrawRectangleRounded(rect(x,y,w,h),.08f,8,c);DrawRectangleRoundedLines(rect(x,y,w,h),.08f,8,Fade(ivory,.13f));}
 bool button(const char*label,float x,float y,float w,float h,bool primary=false){bool hover=inputEnabled&&enabled&&CheckCollisionPointRec(mouse,{x,y,w,h});Color c=primary?(hover?Color{241,201,135,255}:gold):(hover?Color{61,81,79,245}:Color{25,45,47,230});DrawRectangleRounded(rect(x,y,w,h),.14f,8,c);DrawRectangleRoundedLines(rect(x,y,w,h),.14f,8,Fade(primary?gold:ivory,.25f));Vector2 size=MeasureTextEx(fonts.body,label,16*sy,sx);DrawTextEx(fonts.body,label,{(x+w/2)*sx-size.x/2,(y+h/2)*sy-size.y/2},16*sy,sx,primary?dark:ivory);if(hover)SetMouseCursor(MOUSE_CURSOR_POINTING_HAND);return hover&&clicked;}
};
struct Audio {
 bool ready=false,enabled=true;Sound wind{},hit{},grip{};
 Sound synth(int type){const int sr=22050,n=type==0?sr*6:sr/5;std::vector<float> data(n);std::mt19937 gen(842);std::uniform_real_distribution<float> noise(-1,1);float low=0;
  for(int i=0;i<n;i++){float t=i/float(sr);low=low*.97f+noise(gen)*.03f;float fade=type==0?std::min(1.f,std::min(t,float(n-i)/sr)*2):std::exp(-t*25);data[i]=type==0?(low*.22f+std::sin(t*63)*.004f)*fade:(type==1?(low*1.3f+std::sin(t*720)*.17f):(std::sin(t*1700)*.10f+std::sin(t*2300)*.04f))*fade;}
  Wave wave{static_cast<unsigned int>(n),static_cast<unsigned int>(sr),32,1,data.data()};return LoadSoundFromWave(wave);
 }
 Audio(){InitAudioDevice();ready=IsAudioDeviceReady();if(ready){wind=synth(0);hit=synth(1);grip=synth(2);SetSoundVolume(wind,.8f);SetSoundVolume(hit,.3f);SetSoundVolume(grip,.4f);}}
 void update(){if(!ready)return;SetMasterVolume(enabled?1.f:0.f);if(!IsSoundPlaying(wind))PlaySound(wind);}
 void impact(){if(ready&&enabled&&!IsSoundPlaying(hit))PlaySound(hit);}
 void latch(){if(ready&&enabled)PlaySound(grip);}
 ~Audio(){if(ready){UnloadSound(wind);UnloadSound(hit);UnloadSound(grip);CloseAudioDevice();}}
};
struct Particle {ascent::Vec position,velocity;float life,size;};
bool save(const ascent::Player&p,bool sound,float sensitivity){return ascent::writeSave(ascent::defaultSavePath(),p,{sound,sensitivity});}
bool load(ascent::Player&p,bool&sound,float&sensitivity,const std::vector<ascent::Rock>& terrain){ascent::Preferences prefs;if(!ascent::readSave(ascent::defaultSavePath(),p,prefs,terrain))return false;sound=prefs.sound;sensitivity=prefs.sensitivity;return true;}
const char* postFragment=R"(#version 330
in vec2 fragTexCoord;in vec4 fragColor;uniform sampler2D texture0;uniform float time;uniform float warmth;out vec4 finalColor;
void main(){vec2 uv=fragTexCoord;vec3 c=texture(texture0,uv).rgb;float v=1.0-smoothstep(.22,.87,distance(uv,vec2(.50,.49)));c*=.72+.28*v;
float rays=pow(max(0.,1.-distance(uv,vec2(.78,.91))*.91),5.);c+=vec3(.20,.13,.045)*rays*warmth;
float grain=fract(sin(dot(uv*vec2(1440,900)+time,vec2(12.9898,78.233)))*43758.5453);c+=(grain-.5)*.009; c=c/(c+vec3(.55))*1.16;finalColor=vec4(c,1);})";
}
int main(int argc,char**argv){
 bool smoke=false,autoPlay=false;
 std::string smokeScene="intro",capture="ascent-preview.png";
 for(int i=1;i<argc;i++){
  std::string arg=argv[i];
  if(arg=="--smoke-test")smoke=true;
  else if(arg=="--play")autoPlay=true;
  else if(arg.rfind("--scene=",0)==0)smokeScene=arg.substr(8);
  else if(arg.rfind("--capture=",0)==0)capture=arg.substr(10);
 }
 int exitCode=0;
 SetConfigFlags(FLAG_WINDOW_RESIZABLE|FLAG_MSAA_4X_HINT|FLAG_VSYNC_HINT|FLAG_WINDOW_HIGHDPI);
 InitWindow(1280,800,"GETTING OVER IT / THE ASCENT");if(!IsWindowReady())return 1;SetWindowMinSize(960,600);SetExitKey(KEY_NULL);SetTargetFPS(120);
 {
 Fonts fonts;UI ui{fonts};ui.inputEnabled=!smoke;Audio audio;auto terrain=ascent::makeTerrain();World world(terrain);ascent::Player player;float sensitivity=1;bool hasSave=!smoke&&load(player,audio.enabled,sensitivity,terrain);
 enum class Screen {Intro,Playing,Pause,Settings,Help,Restart,Victory};Screen screen=autoPlay?Screen::Playing:Screen::Intro,previous=Screen::Intro;
 if(smoke){
  if(!world.graphicsReady()){TraceLog(LOG_ERROR,"RENDER TEST: shadow framebuffer or shader initialization failed");exitCode=1;}
  if(smokeScene=="heights"||smokeScene=="summit"){
   player.position=smokeScene=="heights"?ascent::Vec{2.2f,25.9f}:ascent::Vec{-1.2f,65.85f};
   player.tip=player.position+ascent::Vec{-1.8f,2.0f};player.best=player.position.y-.55f;player.runBest=player.best;screen=Screen::Playing;
  }else if(smokeScene=="pause")screen=Screen::Pause;
  else if(smokeScene=="settings")screen=Screen::Settings;
  else if(smokeScene=="help")screen=Screen::Help;
  else if(smokeScene=="victory")screen=Screen::Victory;
  else if(smokeScene!="intro"){TraceLog(LOG_ERROR,"RENDER TEST: unknown scene %s",smokeScene.c_str());exitCode=1;}
 }
 RenderTexture2D scene=LoadRenderTexture(GetRenderWidth(),GetRenderHeight());SetTextureFilter(scene.texture,TEXTURE_FILTER_BILINEAR);Shader post=LoadShaderFromMemory(nullptr,postFragment);
 if(smoke&&(!IsRenderTextureValid(scene)||GetShaderLocation(post,"warmth")<0)){TraceLog(LOG_ERROR,"RENDER TEST: scene framebuffer or post shader failed");exitCode=1;}
 Camera3D camera{{-1,7.5f,27},{-1,6.2f,0},{0,1,0},18.5f,CAMERA_ORTHOGRAPHIC};ascent::Vec cameraCenter{-1,6.2f};
 if(smoke&&player.position.y>5){cameraCenter={player.position.x+1,player.position.y+3.4f};camera.target={cameraCenter.x,cameraCenter.y,0};camera.position={cameraCenter.x,cameraCenter.y+1.3f,27};}
 bool victoryAcknowledged=smoke;
 float clock=0,accumulator=0,saveTimer=0,toastTimer=0,fallCooldown=0;int frame=0,stage=player.runBest>44?2:player.runBest>23?1:0;std::string toast;std::vector<Particle> particles;std::mt19937 rng(141);
 bool saveFailed=false;
 auto saveProgress=[&](const ascent::Player& p,bool sound,float sense){
  if(smoke)return true;
  bool success=save(p,sound,sense);saveFailed=!success;if(success)hasSave=true;return success;
 };
 auto notify=[&](std::string message){toast=message;toastTimer=4;};
 auto start=[&](){screen=Screen::Playing;notify("Find your balance. The mountain can wait.");};
 auto pause=[&](){if(screen==Screen::Playing){screen=Screen::Pause;saveProgress(player,audio.enabled,sensitivity);}else if(screen==Screen::Pause)screen=Screen::Playing;};
 while(!WindowShouldClose()){
  float dt=smoke?1.f/60:std::min(GetFrameTime(),.05f);clock+=dt;frame++;toastTimer=std::max(0.f,toastTimer-dt);fallCooldown=std::max(0.f,fallCooldown-dt);ui.begin();SetMouseCursor(MOUSE_CURSOR_DEFAULT);audio.update();
  if(!smoke){
  if(IsKeyPressed(KEY_F11)||(IsKeyDown(KEY_LEFT_ALT)&&IsKeyPressed(KEY_ENTER)))ToggleBorderlessWindowed();
  if(IsKeyPressed(KEY_M))audio.enabled=!audio.enabled;
  if(IsKeyPressed(KEY_ESCAPE)){if(screen==Screen::Settings||screen==Screen::Help||screen==Screen::Restart)screen=previous;else pause();}
  if(IsKeyPressed(KEY_SPACE)&&screen==Screen::Intro)start();
  if(IsKeyPressed(KEY_R)&&screen==Screen::Playing){previous=screen;screen=Screen::Restart;}
  if(IsKeyPressed(KEY_H)){if(screen==Screen::Help)screen=previous;else if(screen==Screen::Intro||screen==Screen::Playing||screen==Screen::Pause){previous=screen;screen=Screen::Help;}}
  }
  if(!smoke&&(IsWindowHidden()||!IsWindowFocused())){if(screen==Screen::Playing)screen=Screen::Pause;}
  bool playing=screen==Screen::Playing&&!smoke;
  if(playing){
   Ray ray=GetScreenToWorldRay(GetMousePosition(),camera);float distance=-ray.position.z/ray.direction.z;Vector3 target=Vector3Add(ray.position,Vector3Scale(ray.direction,distance));
   ascent::Vec desired={(target.x-player.position.x)*sensitivity,(target.y-player.position.y-.55f)*sensitivity};
   bool hold=IsMouseButtonDown(MOUSE_BUTTON_LEFT)||IsKeyDown(KEY_LEFT_SHIFT);accumulator+=dt;
   while(accumulator>=1.f/120){bool wasGrip=player.gripping;float oldImpact=player.impact;float oldY=player.position.y;int oldFalls=player.falls;player.step(1.f/120,desired,hold,terrain);accumulator-=1.f/120;
    if(player.gripping&&!wasGrip){audio.latch();for(int j=0;j<8;j++)particles.push_back({player.tip,{(j-4)*.4f,float(j%3)+1},.5f,.035f});}
    if(player.impact>.45f&&oldImpact<.2f){audio.impact();for(int j=0;j<7;j++)particles.push_back({player.position+ascent::Vec{0,-.5f},{(j-3)*.45f,float(j%3)*.4f},.6f,.045f});}
    if(oldY-player.position.y>.02f&&player.runBest-player.position.y>7&&fallCooldown<=0){notify("A little lower. A little wiser. Keep climbing.");fallCooldown=20;}
    if(player.falls>oldFalls)notify("Back at the beginning. You still have everything you learned.");
   }
   saveTimer+=dt;if(saveTimer>5&&player.grounded){saveProgress(player,audio.enabled,sensitivity);saveTimer=0;}
   int nextStage=player.runBest>44?2:player.runBest>23?1:0;if(nextStage>stage){stage=nextStage;notify(stage==1?"CHAPTER II  /  THE WEATHERED HEIGHTS":"CHAPTER III  /  ABOVE THE CLOUDS");}
   if(player.position.y>65.75f&&!victoryAcknowledged){victoryAcknowledged=true;screen=Screen::Victory;saveProgress(player,audio.enabled,sensitivity);}
  }else accumulator=0;
  for(auto&p:particles){p.life-=dt;p.velocity.y-=6*dt;p.position+=p.velocity*dt;}particles.erase(std::remove_if(particles.begin(),particles.end(),[](auto&p){return p.life<=0;}),particles.end());
  ascent::Vec desiredCamera=screen==Screen::Intro?ascent::Vec{-1,6.2f}:ascent::Vec{std::clamp(player.position.x+1.0f,-4.f,5.f),std::max(6.2f,player.position.y+3.4f)};
  float smoothing=1-std::exp(-dt*3);cameraCenter+= (desiredCamera-cameraCenter)*smoothing;camera.target={cameraCenter.x,cameraCenter.y,0};camera.position={cameraCenter.x,cameraCenter.y+1.3f,27};camera.fovy=screen==Screen::Intro?18.5f:17.f;
  if(scene.texture.width!=GetRenderWidth()||scene.texture.height!=GetRenderHeight()){UnloadRenderTexture(scene);scene=LoadRenderTexture(GetRenderWidth(),GetRenderHeight());SetTextureFilter(scene.texture,TEXTURE_FILTER_BILINEAR);}
  world.renderShadows(camera,player,clock);
  BeginTextureMode(scene);
  float alpine=std::clamp((player.position.y-32.f)/30.f,0.f,1.f);
  Color skyTop=ColorLerp({100,147,159,255},{50,86,117,255},alpine);
  Color skyBottom=ColorLerp({211,218,192,255},{174,193,205,255},alpine);
  ClearBackground(skyTop);DrawRectangleGradientV(0,0,scene.texture.width,scene.texture.height,skyTop,skyBottom);
  // A soft sun disc sits behind the distant peaks.
  Vector2 sun={scene.texture.width*.80f,scene.texture.height*.24f};DrawCircleGradient(int(sun.x),int(sun.y),scene.texture.height*.18f,{252,224,165,90},{252,224,165,0});DrawCircleV(sun,scene.texture.height*.037f,{244,225,181,240});
  BeginMode3D(camera);world.draw(camera,clock,player.position.y);world.player(player,clock);
  for(auto&p:particles)DrawSphere({p.position.x,p.position.y,.7f},p.size,Fade(gold,std::min(1.f,p.life*2)));
  // Slow drifting seeds and snow create depth without obscuring the route.
  for(int i=0;i<60;i++){float x=std::fmod(i*3.713f+clock*(.11f+(i%4)*.03f),34.f)-17+cameraCenter.x;float y=std::fmod(i*1.433f-clock*.12f+200,23.f)-11+cameraCenter.y;float z=1+i%8*.6f;DrawSphere({x,y,z},.012f+(i%3)*.005f,Fade(ivory,.16f+(i%5)*.07f));}
  EndMode3D();EndTextureMode();
  BeginDrawing();ClearBackground(dark);float warmth=1;SetShaderValue(post,GetShaderLocation(post,"time"),&clock,SHADER_UNIFORM_FLOAT);SetShaderValue(post,GetShaderLocation(post,"warmth"),&warmth,SHADER_UNIFORM_FLOAT);BeginShaderMode(post);DrawTexturePro(scene.texture,{0,0,float(scene.texture.width),-float(scene.texture.height)},{0,0,float(GetScreenWidth()),float(GetScreenHeight())},{0,0},0,WHITE);EndShaderMode();
  // Darkened edges hold the typography, while the landscape remains full bleed.
  DrawRectangleGradientV(0,0,GetScreenWidth(),int(145*ui.sy),{12,29,33,150},{12,29,33,0});DrawRectangleGradientV(0,int(730*ui.sy),GetScreenWidth(),int(170*ui.sy),{12,29,33,0},{12,29,33,200});
  // A small mountain monogram.
  DrawLineEx({48*ui.sx,62*ui.sy},{60*ui.sx,42*ui.sy},2*ui.sy,ivory);DrawLineEx({60*ui.sx,42*ui.sy},{72*ui.sx,62*ui.sy},2*ui.sy,ivory);DrawLineEx({64*ui.sx,49*ui.sy},{69*ui.sx,42*ui.sy},2*ui.sy,gold);DrawLineEx({69*ui.sx,42*ui.sy},{81*ui.sx,62*ui.sy},2*ui.sy,gold);
  ui.text("GETTING OVER IT",97,39,17);ui.text("T H E   A S C E N T",98,63,9,muted);
  if(screen==Screen::Intro){ui.text("01",636,48,12,gold);ui.text("THE FOOTHILLS",664,48,11,ivory);ui.line(800,56,34,Fade(ivory,.25f));ui.text("02",854,48,12,Fade(ivory,.35f));ui.text("THE HEIGHTS",881,48,11,Fade(ivory,.35f));}
  ui.enabled=screen==Screen::Intro||screen==Screen::Playing;
  if(ui.button(audio.enabled?"SOUND ON":"SOUND OFF",1110,37,125,37))audio.enabled=!audio.enabled;
  if(ui.button("SETTINGS",1248,37,144,37)&&screen!=Screen::Settings){previous=screen;screen=Screen::Settings;}
  ui.enabled=true;
  if(screen==Screen::Intro){
   // Left-side cinematic scrim.
   DrawRectangleGradientH(0,int(140*ui.sy),int(600*ui.sx),int(565*ui.sy),Fade(dark,.44f),Fade(dark,0));
   ui.line(55,210,36,gold);ui.text("A GAME ABOUT PERSEVERANCE",105,202,11,gold);
   ui.text("One mountain.",52,245,64,ivory,true);ui.text("One hammer.",52,319,64,ivory,true);ui.text("No way but up.",52,393,64,ivory,true);
   ui.text("A quiet place. An impossible climb.",57,491,17,ivory);ui.text("And the stubborn part of you that keeps going.",57,520,16,muted);
   if(ui.button(hasSave?"CONTINUE THE ASCENT    >":"BEGIN THE ASCENT    >",56,579,279,57,true))start();
   if(ui.button("HOW TO PLAY",349,579,155,57)){previous=screen;screen=Screen::Help;}
   ui.text("A MOUSE. A HAMMER. A LITTLE PATIENCE.",57,659,10,Fade(ivory,.58f));
   ui.text("THE FOOTHILLS",1155,718,11,gold);ui.text("Every ascent begins here.",1080,741,18,ivory,true);
  }
  // Expedition instrument panel.
  ui.line(52,789,1336,Fade(ivory,.21f));
  ui.text("ALTITUDE",55,813,10,muted);char buf[128];std::snprintf(buf,sizeof(buf),"%03d",int(std::max(0.f,player.position.y-.55f)*10));ui.text(buf,53,833,30,ivory);ui.text("m",121,849,11,muted);
  ui.text("PERSONAL BEST",190,813,10,muted);std::snprintf(buf,sizeof(buf),"%03d m",int(player.best*10));ui.text(buf,188,838,23,ivory);
  ui.text("EXPEDITION TIME",368,813,10,muted);int seconds=int(player.elapsed);std::snprintf(buf,sizeof(buf),"%02d:%02d:%02d",seconds/3600,seconds/60%60,seconds%60);ui.text(buf,367,838,23,ivory);
  ui.text("THE SUMMIT",1132,813,10,muted);std::snprintf(buf,sizeof(buf),"%d / 660 m",int(player.runBest*10));ui.text(buf,1254,813,11,ivory);ui.line(1133,850,254,Fade(ivory,.2f));ui.line(1133,850,254*std::clamp(player.runBest/66.f,0.f,1.f),gold);
  if(screen==Screen::Playing){
   ui.panel(54,119,212,58,{18,37,39,185});ui.text(stage==0?"I   /   THE FOOTHILLS":stage==1?"II   /   THE HEIGHTS":"III   /   THE SUMMIT",71,140,11,gold);
   if(ui.button("II  PAUSE",1260,112,131,39))pause();
   ui.text(player.gripping?"ANCHORED  /  MOVE TO PULL":"MOVE TO SWING  /  HOLD TO GRIP",545,838,11,player.gripping?gold:muted);
   // A precise reticle stays legible against the terrain.
   Vector2 m=smoke?Vector2{GetScreenWidth()*.58f,GetScreenHeight()*.54f}:GetMousePosition();DrawCircleLines(int(m.x),int(m.y),8*ui.sy,Fade(player.gripping?gold:ivory,.65f));DrawCircleV(m,2*ui.sy,gold);
   if(toastTimer>0){float alpha=std::min(1.f,toastTimer);Vector2 size=MeasureTextEx(fonts.body,toast.c_str(),15*ui.sy,ui.sx);DrawTextEx(fonts.body,toast.c_str(),{GetScreenWidth()/2.f-size.x/2,735*ui.sy},15*ui.sy,ui.sx,Fade(ivory,alpha));}
  }
  bool modal=screen==Screen::Pause||screen==Screen::Settings||screen==Screen::Help||screen==Screen::Restart||screen==Screen::Victory;
  if(modal){
   DrawRectangle(0,0,GetScreenWidth(),GetScreenHeight(),{7,20,24,185});ui.panel(440,181,560,535,{20,39,42,248});
   const char*title=screen==Screen::Pause?"Take a breath.":screen==Screen::Settings?"Make it yours.":screen==Screen::Help?"Find your foothold.":screen==Screen::Restart?"Begin again?":"You got over it.";
   ui.text("T H E   A S C E N T",481,219,10,gold);ui.text(title,479,260,40,ivory,true);ui.line(480,323,480,Fade(ivory,.18f));
   if(screen==Screen::Pause){ui.text("The mountain will still be here.",481,350,17,muted);if(ui.button("RESUME THE CLIMB",480,400,480,53,true))screen=Screen::Playing;if(ui.button("HOW TO PLAY",480,468,232,46)){previous=screen;screen=Screen::Help;}if(ui.button("SETTINGS",728,468,232,46)){previous=screen;screen=Screen::Settings;}if(ui.button("START AGAIN",480,530,480,46)){previous=screen;screen=Screen::Restart;}if(ui.button("SAVE & QUIT",480,625,480,45)){if(saveProgress(player,audio.enabled,sensitivity))break;}ui.text(saveFailed?"SAVE FAILED / TRY AGAIN BEFORE QUITTING":"ESC TO RESUME",saveFailed?500:657,592,10,saveFailed?gold:muted);}
   if(screen==Screen::Settings){ui.text("AMBIENT SOUND",481,354,13,ivory);if(ui.button(audio.enabled?"ON":"OFF",840,344,120,40))audio.enabled=!audio.enabled;ui.text("MOUSE SENSITIVITY",481,422,13,ivory);std::snprintf(buf,sizeof(buf),"%.1fx",sensitivity);ui.text(buf,771,422,14,gold);if(ui.button("-",840,408,52,40))sensitivity=std::max(.5f,sensitivity-.1f);if(ui.button("+",908,408,52,40))sensitivity=std::min(1.5f,sensitivity+.1f);ui.text("DISPLAY",481,490,13,ivory);if(ui.button("TOGGLE FULLSCREEN",725,476,235,42))ToggleBorderlessWindowed();ui.text("F11 fullscreen    /    M mute    /    ESC back",481,564,12,muted);if(ui.button("BACK TO THE MOUNTAIN",480,625,480,45,true)){saveProgress(player,audio.enabled,sensitivity);screen=previous;}}
   if(screen==Screen::Help){const char*labels[]={"01   SWING","02   ANCHOR","03   PUSH & PULL"};const char*details[]={"Move the mouse to guide your hammer.","Hold left mouse (or Shift) against a rock.","Move toward the anchor to extend and push.\nMove away to pull yourself up. Release to swing."};for(int i=0;i<3;i++){ui.text(labels[i],481,349+i*77,11,gold);ui.text(details[i],481,373+i*77,14,ivory);}ui.text("No jumps. No shortcuts. Progress saves automatically.",481,595,12,muted);if(ui.button("I'M READY",480,641,480,43,true))screen=previous;}
   if(screen==Screen::Restart){ui.text("Your current climb will return to the foothills.",481,355,16,ivory);ui.text("Your personal best stays with you.",481,387,16,muted);if(ui.button("KEEP CLIMBING",480,468,480,50,true))screen=previous;if(ui.button("START A FRESH ASCENT",480,536,480,46)){float best=player.best;player.reset();victoryAcknowledged=false;player.best=best;stage=0;screen=Screen::Playing;saveProgress(player,audio.enabled,sensitivity);}}
   if(screen==Screen::Victory){ui.text("660 METRES. EVERY ONE EARNED.",481,355,12,gold);ui.text("The view was always waiting for you.",481,397,20,ivory,true);ui.text("Take a moment. You made it.",481,437,17,muted);if(ui.button("ONE MORE ASCENT",480,534,480,50,true)){float best=player.best;player.reset();victoryAcknowledged=false;player.best=best;screen=Screen::Playing;stage=0;saveProgress(player,audio.enabled,sensitivity);}if(ui.button("STAY A WHILE",480,602,480,45))screen=Screen::Playing;}
  }
  if(saveFailed&&screen==Screen::Playing)ui.text("PROGRESS COULD NOT BE SAVED",550,705,12,gold);
  EndDrawing();
  if(smoke&&frame==12){Image screenshot=LoadImageFromScreen();bool exported=ExportImage(screenshot,capture.c_str());UnloadImage(screenshot);if(!exported)exitCode=1;TraceLog(LOG_INFO,"RENDER TEST: %s, framebuffer %d x %d",exitCode?"FAILED":"PASSED",scene.texture.width,scene.texture.height);break;}
 }
 if(!smoke)saveProgress(player,audio.enabled,sensitivity);UnloadRenderTexture(scene);UnloadShader(post);
 }
 CloseWindow();return exitCode;
}
