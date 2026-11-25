// SoundTouch / Rubber Band seek-reset experiment.
// Build:
//   clang++ -std=c++17 -O2 -I/opt/homebrew/opt/sound-touch/include \
//     -I/opt/homebrew/opt/rubberband/include seek_dsp.cpp \
//     -L/opt/homebrew/opt/sound-touch/lib -L/opt/homebrew/opt/rubberband/lib \
//     -lSoundTouch -lrubberband -o seek_dsp
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include <rubberband/RubberBandStretcher.h>
#include <soundtouch/SoundTouch.h>

struct Wav {
    int rate = 0;
    int channels = 0;
    std::vector<float> mono;
};

static uint32_t le32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint16_t le16(const unsigned char *p) {
    return (uint16_t)(p[0] | (p[1] << 8));
}

static Wav load_wav(const std::string &path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("cannot open " + path);
    std::vector<unsigned char> b((std::istreambuf_iterator<char>(f)), {});
    if (b.size() < 44 || memcmp(b.data(), "RIFF", 4) || memcmp(b.data() + 8, "WAVE", 4))
        throw std::runtime_error("not a RIFF/WAVE file");
    Wav w;
    size_t p = 12;
    int bits = 0;
    const unsigned char *data = nullptr;
    size_t data_size = 0;
    while (p + 8 <= b.size()) {
        uint32_t sz = le32(&b[p + 4]);
        const unsigned char *chunk = &b[p + 8];
        if (p + 8 + sz > b.size()) sz = (uint32_t)(b.size() - p - 8);
        if (!memcmp(&b[p], "fmt ", 4) && sz >= 16) {
            uint16_t fmt = le16(chunk);
            w.channels = le16(chunk + 2);
            w.rate = (int)le32(chunk + 4);
            bits = le16(chunk + 14);
            if (fmt != 1 || bits != 16) throw std::runtime_error("need PCM16 WAV");
        } else if (!memcmp(&b[p], "data", 4)) {
            data = chunk;
            data_size = sz;
        }
        p += 8 + sz + (sz & 1);
    }
    if (!data || w.channels <= 0 || w.rate <= 0)
        throw std::runtime_error("missing fmt/data");
    size_t frames = data_size / (2 * w.channels);
    w.mono.resize(frames);
    const int16_t *s = reinterpret_cast<const int16_t *>(data);
    for (size_t i = 0; i < frames; i++) {
        float v = 0;
        for (int c = 0; c < w.channels; c++) v += s[i * w.channels + c] / 32768.0f;
        w.mono[i] = v / w.channels;
    }
    return w;
}

static size_t first_click(const std::vector<float> &x, float threshold = 0.2f) {
    for (size_t i = 0; i < x.size(); i++)
        if (std::fabs(x[i]) >= threshold) return i;
    return x.size();
}

struct Result {
    std::string engine;
    double speed = 1;
    double target = 0;
    double expected = 0;
    double actual = 0;
    double error_ms = 0;
    double first_out_ms = 0;
    double process_ms = 0;
    size_t out_samples = 0;
};

static Result soundtouch_run(const Wav &w, double speed, double target_s) {
    const int rate = w.rate;
    const size_t start = (size_t)std::llround(target_s * rate);
    const double expected = std::ceil((target_s + 1e-9) / 0.5) * 0.5;
    const size_t need_input = std::min(w.mono.size(), start + (size_t)(rate * 3));
    const size_t chunk = 1024;
    soundtouch::SoundTouch st;
    st.setSampleRate(rate);
    st.setChannels(1);
    st.setTempo(speed);
    st.setPitch(1.0);
    st.setRate(1.0);
    std::vector<float> out;
    out.reserve(rate * 4);
    std::vector<float> tmp(chunk * 2);
    auto t0 = std::chrono::steady_clock::now();
    size_t pos = start;
    while (pos < need_input || out.size() < rate * 2) {
        size_t n = std::min(chunk, need_input - pos);
        if (n == 0) break;
        st.putSamples(w.mono.data() + pos, (uint)n);
        pos += n;
        uint got;
        while ((got = st.receiveSamples(tmp.data(), (uint)tmp.size())) > 0)
            out.insert(out.end(), tmp.begin(), tmp.begin() + got);
        if (out.size() > rate * 4) break;
    }
    auto t1 = std::chrono::steady_clock::now();
    size_t fc = first_click(out);
    Result r;
    r.engine = "SoundTouch";
    r.speed = speed;
    r.target = target_s;
    r.expected = expected;
    r.actual = target_s + (double)fc / rate * speed;
    r.error_ms = (r.actual - expected) * 1000;
    r.first_out_ms = (double)fc / rate * 1000;
    r.process_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    r.out_samples = out.size();
    return r;
}

static Result rubber_run(const Wav &w, double speed, double target_s) {
    const int rate = w.rate;
    const size_t start = (size_t)std::llround(target_s * rate);
    const double expected = std::ceil((target_s + 1e-9) / 0.5) * 0.5;
    const size_t need_input = std::min(w.mono.size(), start + (size_t)(rate * 3));
    const size_t chunk = 1024;
    RubberBand::RubberBandStretcher rb(
        (size_t)rate, 1,
        RubberBand::RubberBandStretcher::OptionProcessRealTime |
        RubberBand::RubberBandStretcher::OptionEngineFiner,
        1.0 / speed, 1.0);
    std::vector<float> out;
    out.reserve(rate * 4);
    auto t0 = std::chrono::steady_clock::now();
    size_t pos = start;
    while (pos < need_input || out.size() < rate * 2) {
        size_t n = std::min(chunk, need_input - pos);
        if (n == 0) break;
        const float *in[1] = {w.mono.data() + pos};
        rb.process(in, n, false);
        pos += n;
        size_t avail = rb.available();
        if (avail) {
            size_t at = out.size();
            out.resize(at + avail);
            float *o[1] = {out.data() + at};
            rb.retrieve(o, avail);
        }
        if (out.size() > rate * 4) break;
    }
    auto t1 = std::chrono::steady_clock::now();
    size_t fc = first_click(out);
    Result r;
    r.engine = "Rubber Band R3";
    r.speed = speed;
    r.target = target_s;
    r.expected = expected;
    r.actual = target_s + (double)fc / rate * speed;
    r.error_ms = (r.actual - expected) * 1000;
    r.first_out_ms = (double)fc / rate * 1000;
    r.process_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    r.out_samples = out.size();
    return r;
}

int main(int argc, char **argv) {
    std::string input = "click.wav";
    std::vector<double> speeds = {1.0, 0.8, 0.65};
    std::vector<double> targets = {1.03, 4.27, 7.51};
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--input") && i + 1 < argc) input = argv[++i];
    }
    try {
        Wav w = load_wav(input);
        std::cout << "engine,speed,target,expected,actual,error_ms,first_out_ms,process_ms,out_samples\n";
        for (double speed : speeds) {
            for (double target : targets) {
                auto a = soundtouch_run(w, speed, target);
                auto b = rubber_run(w, speed, target);
                for (auto *r : {&a, &b}) {
                    char buf[512];
                    std::snprintf(buf, sizeof(buf),
                        "%s,%.2f,%.2f,%.3f,%.3f,%.3f,%.3f,%.3f,%zu\n",
                        r->engine.c_str(), r->speed, r->target, r->expected,
                        r->actual, r->error_ms, r->first_out_ms,
                        r->process_ms, r->out_samples);
                    std::cout << buf;
                }
            }
        }
    } catch (const std::exception &e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
