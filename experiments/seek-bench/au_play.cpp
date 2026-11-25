// Play a WAV to BlackHole via an AudioUnit output, for loopback latency tests.
#include <AudioToolbox/AudioToolbox.h>
#include <AudioUnit/AudioUnit.h>
#include <CoreAudio/CoreAudio.h>
#include <CoreFoundation/CoreFoundation.h>
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
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("cannot open "+path);
    std::vector<unsigned char> b((std::istreambuf_iterator<char>(f)), {});
    if (b.size()<44 || memcmp(b.data(),"RIFF",4) || memcmp(b.data()+8,"WAVE",4)) throw std::runtime_error("not WAVE");
    Wav w; size_t p=12; const unsigned char *data=nullptr; size_t data_size=0; int bits=0;
    while (p+8<=b.size()) {
        uint32_t sz=le32(&b[p+4]); const unsigned char *chunk=&b[p+8];
        if (p+8+sz>b.size()) sz=(uint32_t)(b.size()-p-8);
        if (!memcmp(&b[p],"fmt ",4)&&sz>=16) { w.channels=le16(chunk+2); w.rate=(int)le32(chunk+4); bits=le16(chunk+14); }
        else if (!memcmp(&b[p],"data",4)) { data=chunk; data_size=sz; }
        p += 8+sz+(sz&1);
    }
    if (!data || bits!=16 || w.channels<1) throw std::runtime_error("need PCM16");
    size_t frames=data_size/(2*w.channels); w.mono.resize(frames);
    const int16_t *s=reinterpret_cast<const int16_t*>(data);
    for (size_t i=0;i<frames;i++) { float v=0; for (int c=0;c<w.channels;c++) v+=s[i*w.channels+c]/32768.0f; w.mono[i]=v/w.channels; }
    return w;
}
static AudioDeviceID find_device(const std::string &wanted) {
    AudioObjectPropertyAddress a{kAudioHardwarePropertyDevices,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
    UInt32 size=0; if (AudioObjectGetPropertyDataSize(kAudioObjectSystemObject,&a,0,nullptr,&size)!=noErr) return kAudioObjectUnknown;
    std::vector<AudioDeviceID> ids(size/sizeof(AudioDeviceID));
    if (AudioObjectGetPropertyData(kAudioObjectSystemObject,&a,0,nullptr,&size,ids.data())!=noErr) return kAudioObjectUnknown;
    for (auto id:ids) {
        CFStringRef name=nullptr; UInt32 n=sizeof(name);
        AudioObjectPropertyAddress na{kAudioObjectPropertyName,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
        if (AudioObjectGetPropertyData(id,&na,0,nullptr,&n,&name)!=noErr || !name) continue;
        char buf[256]={0}; CFStringGetCString(name,buf,sizeof(buf),kCFStringEncodingUTF8); CFRelease(name);
        if (wanted.empty() || std::string(buf).find(wanted)!=std::string::npos) return id;
    }
    return kAudioObjectUnknown;
}

static std::vector<float> g_audio;
static std::atomic<size_t> g_pos{0};
static OSStatus render(void *inRef, AudioUnitRenderActionFlags *, const AudioTimeStamp *,
                       UInt32, UInt32 frames, AudioBufferList *io) {
    auto *out = reinterpret_cast<float *>(io->mBuffers[0].mData);
    size_t p = g_pos.load(std::memory_order_relaxed);
    size_t total = g_audio.size() / 2;
    for (UInt32 i=0;i<frames;i++) {
        float l=0, r=0;
        if (p+i<total) { l=g_audio[(p+i)*2]; r=g_audio[(p+i)*2+1]; }
        out[i*2]=l; out[i*2+1]=r;
    }
    g_pos.store(p+frames, std::memory_order_relaxed);
    io->mBuffers[0].mDataByteSize = frames*8;
    return noErr;
}

int main(int argc, char **argv) {
    std::string input="click.wav", device="BlackHole"; double target=0;
    for (int i=1;i<argc;i++) {
        if (!strcmp(argv[i],"--input") && i+1<argc) input=argv[++i];
        else if (!strcmp(argv[i],"--device") && i+1<argc) device=argv[++i];
        else if (!strcmp(argv[i],"--target") && i+1<argc) target=std::stod(argv[++i]);
    }
    try {
        Wav w=load_wav(input);
        size_t start=(size_t)std::llround(target*w.rate);
        if (start>=w.mono.size()) throw std::runtime_error("target past end");
        size_t frames=std::min<size_t>(w.mono.size()-start,(size_t)(w.rate*2.0));
        g_audio.resize(frames*2);
        for (size_t i=0;i<frames;i++) g_audio[i*2]=g_audio[i*2+1]=w.mono[start+i];

        AudioDeviceID dev=find_device(device);
        if (dev==kAudioObjectUnknown) throw std::runtime_error("device not found: "+device);
        AudioComponentDescription cd{};
        cd.componentType=kAudioUnitType_Output; cd.componentSubType=kAudioUnitSubType_DefaultOutput;
        cd.componentManufacturer=kAudioUnitManufacturer_Apple;
        AudioComponent comp=AudioComponentFindNext(nullptr,&cd);
        if (!comp) throw std::runtime_error("no output AudioUnit");
        AudioUnit au=nullptr;
        if (AudioComponentInstanceNew(comp,&au)!=noErr) throw std::runtime_error("AudioComponentInstanceNew failed");
        OSStatus st=AudioUnitSetProperty(au,kAudioOutputUnitProperty_CurrentDevice,
                                         kAudioUnitScope_Global,0,&dev,sizeof(dev));
        if (st!=noErr) throw std::runtime_error("set device failed: "+std::to_string(st));
        AudioStreamBasicDescription fmt{};
        fmt.mSampleRate=w.rate; fmt.mFormatID=kAudioFormatLinearPCM;
        fmt.mFormatFlags=kAudioFormatFlagIsFloat|kAudioFormatFlagIsPacked;
        fmt.mFramesPerPacket=1; fmt.mChannelsPerFrame=2; fmt.mBitsPerChannel=32;
        fmt.mBytesPerFrame=8; fmt.mBytesPerPacket=8;
        st=AudioUnitSetProperty(au,kAudioUnitProperty_StreamFormat,kAudioUnitScope_Input,0,&fmt,sizeof(fmt));
        if (st!=noErr) throw std::runtime_error("set format failed: "+std::to_string(st));
        AURenderCallbackStruct cb{render,nullptr};
        st=AudioUnitSetProperty(au,kAudioUnitProperty_SetRenderCallback,kAudioUnitScope_Input,0,&cb,sizeof(cb));
        if (st!=noErr) throw std::runtime_error("set callback failed");
        st=AudioUnitInitialize(au); if (st!=noErr) throw std::runtime_error("initialize failed");
        auto t0=std::chrono::steady_clock::now();
        st=AudioOutputUnitStart(au); if (st!=noErr) throw std::runtime_error("start failed");
        std::cout<<"START_NS "<<std::chrono::duration_cast<std::chrono::nanoseconds>(t0.time_since_epoch()).count()<<"\n";
        std::cout.flush();
        std::this_thread::sleep_for(std::chrono::milliseconds((long)(frames*1000/w.rate)+300));
        AudioOutputUnitStop(au); AudioUnitUninitialize(au); AudioComponentInstanceDispose(au);
    } catch (const std::exception &e) { std::cerr<<e.what()<<"\n"; return 1; }
    return 0;
}
