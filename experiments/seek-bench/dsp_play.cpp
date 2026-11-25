// Prepare a short seek window with SoundTouch / Rubber Band, then play it to BlackHole.
#include <AudioToolbox/AudioToolbox.h>
#include <AudioUnit/AudioUnit.h>
#include <CoreAudio/CoreAudio.h>
#include <CoreFoundation/CoreFoundation.h>
#include <rubberband/RubberBandStretcher.h>
#include <soundtouch/SoundTouch.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

static uint32_t le32(const unsigned char *p) { return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
static uint16_t le16(const unsigned char *p) { return (uint16_t)(p[0]|(p[1]<<8)); }
struct Wav { int rate=44100; int channels=1; std::vector<float> mono; };
static Wav load_wav(const std::string &path) {
    std::ifstream f(path, std::ios::binary); if (!f) throw std::runtime_error("cannot open "+path);
    std::vector<unsigned char> b((std::istreambuf_iterator<char>(f)), {});
    if (b.size()<44 || memcmp(b.data(),"RIFF",4) || memcmp(b.data()+8,"WAVE",4)) throw std::runtime_error("not WAVE");
    Wav w; size_t p=12; const unsigned char *data=nullptr; size_t ds=0; int bits=0;
    while (p+8<=b.size()) { uint32_t sz=le32(&b[p+4]); const unsigned char *c=&b[p+8]; if (p+8+sz>b.size()) sz=(uint32_t)(b.size()-p-8);
        if (!memcmp(&b[p],"fmt ",4)&&sz>=16) { w.channels=le16(c+2); w.rate=(int)le32(c+4); bits=le16(c+14); }
        else if (!memcmp(&b[p],"data",4)) { data=c; ds=sz; } p+=8+sz+(sz&1); }
    if (!data || bits!=16 || w.channels<1) throw std::runtime_error("need PCM16");
    size_t n=ds/(2*w.channels); w.mono.resize(n); const int16_t *s=reinterpret_cast<const int16_t*>(data);
    for (size_t i=0;i<n;i++) { float v=0; for (int c=0;c<w.channels;c++) v+=s[i*w.channels+c]/32768.0f; w.mono[i]=v/w.channels; }
    return w;
}
static AudioDeviceID find_device(const std::string &wanted) {
    AudioObjectPropertyAddress a{kAudioHardwarePropertyDevices,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
    UInt32 size=0; if (AudioObjectGetPropertyDataSize(kAudioObjectSystemObject,&a,0,nullptr,&size)!=noErr) return kAudioObjectUnknown;
    std::vector<AudioDeviceID> ids(size/sizeof(AudioDeviceID));
    if (AudioObjectGetPropertyData(kAudioObjectSystemObject,&a,0,nullptr,&size,ids.data())!=noErr) return kAudioObjectUnknown;
    for (auto id:ids) { CFStringRef name=nullptr; UInt32 n=sizeof(name); AudioObjectPropertyAddress na{kAudioObjectPropertyName,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
        if (AudioObjectGetPropertyData(id,&na,0,nullptr,&n,&name)!=noErr || !name) continue; char buf[256]={0}; CFStringGetCString(name,buf,sizeof(buf),kCFStringEncodingUTF8); CFRelease(name);
        if (wanted.empty() || std::string(buf).find(wanted)!=std::string::npos) return id; }
    return kAudioObjectUnknown;
}
static std::vector<float> prepare(const Wav &w, double target, double speed, const std::string &engine) {
    size_t start=(size_t)std::llround(target*w.rate);
    if (start>=w.mono.size()) throw std::runtime_error("target past end");
    if (engine=="native") {
        size_t n=std::min<size_t>(w.mono.size()-start,(size_t)(w.rate*2.0));
        return std::vector<float>(w.mono.begin()+start,w.mono.begin()+start+n);
    }
    if (engine=="soundtouch") {
        soundtouch::SoundTouch st; st.setSampleRate(w.rate); st.setChannels(1);
        st.setTempo(speed); st.setPitch(1.0); st.setRate(1.0);
        std::vector<float> out, tmp(4096); size_t pos=start; size_t need=std::min(w.mono.size(),start+(size_t)(w.rate*3));
        while (pos<need || out.size()<w.rate*2) {
            size_t n=std::min<size_t>(1024,need-pos); if(!n) break;
            st.putSamples(w.mono.data()+pos,(uint)n); pos+=n;
            uint got; while ((got=st.receiveSamples(tmp.data(),(uint)tmp.size()))>0) out.insert(out.end(),tmp.begin(),tmp.begin()+got);
            if(out.size()>w.rate*3) break;
        }
        return out;
    }
    if (engine=="rubberband") {
        RubberBand::RubberBandStretcher rb((size_t)w.rate,1,
            RubberBand::RubberBandStretcher::OptionProcessRealTime|RubberBand::RubberBandStretcher::OptionEngineFiner,
            1.0/speed,1.0);
        std::vector<float> out; size_t pos=start; size_t need=std::min(w.mono.size(),start+(size_t)(w.rate*3));
        while (pos<need || out.size()<w.rate*2) {
            size_t n=std::min<size_t>(1024,need-pos); if(!n) break;
            const float *in[1]={w.mono.data()+pos}; rb.process(in,n,false); pos+=n;
            size_t avail=rb.available(); if(avail) { size_t at=out.size(); out.resize(at+avail); float *o[1]={out.data()+at}; rb.retrieve(o,avail); }
            if(out.size()>w.rate*3) break;
        }
        return out;
    }
    throw std::runtime_error("unknown engine");
}
static std::vector<float> g_audio; static std::atomic<size_t> g_pos{0};
static OSStatus render(void *, AudioUnitRenderActionFlags *, const AudioTimeStamp *, UInt32, UInt32 frames, AudioBufferList *io) {
    auto *out=reinterpret_cast<float*>(io->mBuffers[0].mData); size_t p=g_pos.load(); size_t total=g_audio.size();
    for (UInt32 i=0;i<frames;i++) { float v=(p+i<total)?g_audio[p+i]:0; out[i*2]=v; out[i*2+1]=v; }
    g_pos.store(p+frames); io->mBuffers[0].mDataByteSize=frames*8; return noErr;
}
int main(int argc,char**argv){
    std::string input="click.wav", device="BlackHole", engine="native"; double target=1.0, speed=0.8;
    for(int i=1;i<argc;i++){ if(!strcmp(argv[i],"--input")&&i+1<argc)input=argv[++i]; else if(!strcmp(argv[i],"--device")&&i+1<argc)device=argv[++i];
        else if(!strcmp(argv[i],"--engine")&&i+1<argc)engine=argv[++i]; else if(!strcmp(argv[i],"--target")&&i+1<argc)target=std::stod(argv[++i]); else if(!strcmp(argv[i],"--speed")&&i+1<argc)speed=std::stod(argv[++i]); }
    try {
        Wav w=load_wav(input); auto t0=std::chrono::steady_clock::now();
        g_audio=prepare(w,target,speed,engine); auto t1=std::chrono::steady_clock::now();
        std::cout<<"PREP_MS "<<std::chrono::duration<double,std::milli>(t1-t0).count()<<"\n";
        AudioDeviceID dev=find_device(device); if(dev==kAudioObjectUnknown) throw std::runtime_error("device not found");
        AudioComponentDescription cd{}; cd.componentType=kAudioUnitType_Output; cd.componentSubType=kAudioUnitSubType_DefaultOutput; cd.componentManufacturer=kAudioUnitManufacturer_Apple;
        AudioComponent comp=AudioComponentFindNext(nullptr,&cd); if(!comp) throw std::runtime_error("no output unit");
        AudioUnit au=nullptr; if(AudioComponentInstanceNew(comp,&au)!=noErr) throw std::runtime_error("new unit failed");
        OSStatus st=AudioUnitSetProperty(au,kAudioOutputUnitProperty_CurrentDevice,kAudioUnitScope_Global,0,&dev,sizeof(dev)); if(st!=noErr) throw std::runtime_error("set device failed");
        AudioStreamBasicDescription fmt{}; fmt.mSampleRate=w.rate; fmt.mFormatID=kAudioFormatLinearPCM; fmt.mFormatFlags=kAudioFormatFlagIsFloat|kAudioFormatFlagIsPacked; fmt.mFramesPerPacket=1; fmt.mChannelsPerFrame=2; fmt.mBitsPerChannel=32; fmt.mBytesPerFrame=8; fmt.mBytesPerPacket=8;
        st=AudioUnitSetProperty(au,kAudioUnitProperty_StreamFormat,kAudioUnitScope_Input,0,&fmt,sizeof(fmt)); if(st!=noErr) throw std::runtime_error("set format failed");
        AURenderCallbackStruct cb{render,nullptr}; st=AudioUnitSetProperty(au,kAudioUnitProperty_SetRenderCallback,kAudioUnitScope_Input,0,&cb,sizeof(cb)); if(st!=noErr) throw std::runtime_error("set callback failed");
        if(AudioUnitInitialize(au)!=noErr) throw std::runtime_error("init failed");
        auto t2=std::chrono::steady_clock::now(); st=AudioOutputUnitStart(au); if(st!=noErr) throw std::runtime_error("start failed");
        std::cout<<"START_NS "<<std::chrono::duration_cast<std::chrono::nanoseconds>(t2.time_since_epoch()).count()<<"\n"; std::cout.flush();
        std::this_thread::sleep_for(std::chrono::milliseconds((long)(g_audio.size()*1000/w.rate)+300));
        AudioOutputUnitStop(au); AudioUnitUninitialize(au); AudioComponentInstanceDispose(au);
    } catch(const std::exception&e){ std::cerr<<e.what()<<"\n"; return 1; }
    return 0;
}
