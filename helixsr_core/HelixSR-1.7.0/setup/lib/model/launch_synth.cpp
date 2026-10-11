// Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
//
// launch_synth: a synthetic launch capture (manifest.txt, args.bin, alloc-*.bin) of one network kernel, built from
// HelixSR's host model alone: the argument block and buffer layout of the kernel's launch at a given frame shape, every
// buffer filled with random bytes. Tools that only need a launch's layout (the fragment tracer) run on it instead of a
// recorded launch.
// Usage: launch_synth <out dir> <kernel name> <Wo> <Ho> <Wr> <Hr> [occurrence]
#include "model.h"
#include <cstdio>
#include <filesystem>
#include <cstdlib>
#include <cstring>
#include <map>
#include <random>
#include <string>

using namespace bcm;

int main(int argc, char** argv)
{
    if (argc < 7)
    {
        fprintf(stderr, "usage: launch_synth <out dir> <kernel> <Wo> <Ho> <Wr> <Hr> [occurrence]\n");
        return 2;
    }
    const std::string out = argv[1], kernel = argv[2];
    Params P;
    P.Wo = atoi(argv[3]), P.Ho = atoi(argv[4]), P.Wr = atoi(argv[5]), P.Hr = atoi(argv[6]);
    const uint32_t occurrence = argc > 7 ? atoi(argv[7]) : 0;
    P.net = network_for(P.Wo, P.Ho, P.Wr, P.Hr);
    finalize(P);
    const NetTables& nt = net_tables(P.net);
    // frame 1: every network kernel runs (frame 0 adds the clear only)
    for (const Launch& L : plan(P, 1))
    {
        if (kernel != L.name || L.occurrence != occurrence)
            continue;
        std::filesystem::create_directories(out);
        std::mt19937_64 rng(1234);
        std::map<std::pair<int, int>, int> allocOf;   // (kind, role or weight index) -> alloc id
        std::vector<std::pair<uint64_t, uint64_t>> allocs;   // base, size
        std::vector<uint8_t> args = L.args;
        std::string ptrs;
        uint64_t next = 0x7f0000000000ull;
        for (const LaunchBinding& b : L.bindings)
        {
            uint64_t size = 0;
            int key = b.role;
            if (b.kind == BindBuffer)
                size = nt.buffers[b.role].bytes(P);
            else if (b.kind == BindWeight)
                size = b.weightSize, key = (int)b.offset;   // one allocation per weight tensor
            else
                continue;   // texture/surface parameters: not used by the traced kernels
            auto it = allocOf.find({b.kind, key});
            if (it == allocOf.end())
            {
                it = allocOf.emplace(std::make_pair((int)b.kind, key), (int)allocs.size()).first;
                allocs.push_back({next, size});
                next += (size + 0xfffff) & ~0xfffffull;
            }
            const uint64_t off = b.kind == BindBuffer ? b.offset : 0;
            const uint64_t ptr = allocs[it->second].first + off;
            memcpy(args.data() + b.argOffset, &ptr, 8);
            ptrs += "pointer " + std::to_string(b.argOffset) + " " + std::to_string(it->second) + " " +
                    std::to_string(off) + "\n";
        }
        FILE* m = fopen((out + "/manifest.txt").c_str(), "w");
        fprintf(m, "replay_version 2\nkernel %s\nlaunch %u %u %u %u %u %u 0\nargs %zu\n", L.name, L.grid[0], L.grid[1],
                L.grid[2], L.block[0], L.block[1], L.block[2], args.size());
        for (size_t i = 0; i < allocs.size(); ++i)
        {
            fprintf(m, "alloc %zu 0x%llx %llu\n", i, (unsigned long long)allocs[i].first,
                    (unsigned long long)allocs[i].second);
            std::vector<uint8_t> data(allocs[i].second);
            for (auto& x : data)
                x = (uint8_t)rng();
            FILE* f = fopen((out + "/alloc-" + std::to_string(i) + ".bin").c_str(), "wb");
            fwrite(data.data(), 1, data.size(), f);
            fclose(f);
        }
        fputs(ptrs.c_str(), m);
        fclose(m);
        FILE* a = fopen((out + "/args.bin").c_str(), "wb");
        fwrite(args.data(), 1, args.size(), a);
        fclose(a);
        fclose(fopen((out + "/COMPLETE").c_str(), "w"));
        printf("%s: grid %u %u %u, %zu args bytes, %zu allocations\n", L.name, L.grid[0], L.grid[1], L.grid[2],
               args.size(), allocs.size());
        return 0;
    }
    fprintf(stderr, "kernel %s (occurrence %u) not in the plan for %ux%u -> %ux%u\n", kernel.c_str(), occurrence,
            P.Wr, P.Hr, P.Wo, P.Ho);
    return 1;
}
