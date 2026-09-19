#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

// New implementation of the supplied FAM-001 v1.1 declarative definition.
// Matrix construction uses exact counts of (q, Greek rank) at aligned
// positions within units. It evaluates every affine rule from those counts.
// The separate direct observed check evaluates literal predictions anew.
using U8 = uint8_t;
using U32 = uint32_t;
using I64 = int64_t;
constexpr size_t U = 16, A = 24;

U32 read32(std::istream& f) {
    unsigned char b[4]; f.read(reinterpret_cast<char*>(b), 4);
    if (!f) throw std::runtime_error("Truncated uint32");
    return U32(b[0]) | U32(b[1]) << 8 | U32(b[2]) << 16 | U32(b[3]) << 24;
}
void write32(std::ostream& f, U32 n) {
    unsigned char b[4] = {U8(n), U8(n >> 8), U8(n >> 16), U8(n >> 24)};
    f.write(reinterpret_cast<char*>(b), 4);
}
std::vector<int> readList(std::istream& f, bool signed_values = false) {
    U32 n = read32(f); if (n > 100) throw std::runtime_error("Bad parameter count");
    std::vector<int> result(n);
    for (auto& x : result) {
        U32 v = read32(f);
        x = signed_values && v == 0xffffffffU ? -1 : int(v);
    }
    return result;
}
std::vector<U8> readBytes(std::istream& f, size_t n) {
    std::vector<U8> b(n); f.read(reinterpret_cast<char*>(b.data()), n);
    if (!f) throw std::runtime_error("Truncated byte array"); return b;
}
struct Rule {
    int direction, offset, multiplier, intercept;
    std::array<U32, U*U> matrix{};
    I64 total = 0, observed = 0, score = 0;
};

int main(int argc, char** argv) {
    try {
        if (argc != 3) throw std::runtime_error("Usage: engine INPUT.bin OUTPUT_PREFIX");
        auto start = std::chrono::steady_clock::now();
        std::ifstream f(argv[1], std::ios::binary);
        auto magic = readBytes(f, 8);
        if (std::string(magic.begin(), magic.end()) != "FAM001I1") throw std::runtime_error("Wrong input magic");
        U32 H = read32(f), N = read32(f), R = read32(f);
        if (!H || !N || N % U) throw std::runtime_error("Invalid stream lengths");
        auto directions = readList(f, true), offsets = readList(f), multipliers = readList(f), intercepts = readList(f);
        if (directions != std::vector<int>{1,-1} || offsets != std::vector<int>{0,1,2,3,4,5,6,7} ||
            multipliers != std::vector<int>{1,5,7,11,13,17,19,23}) throw std::runtime_error("Unexpected grammar");
        for (int b = 0; b < 24; ++b) if (intercepts.size() != 24 || intercepts[b] != b) throw std::runtime_error("Unexpected intercepts");
        auto h = readBytes(f, H), g = readBytes(f, N), refs = readBytes(f, size_t(R)*U);
        if (f.peek() != EOF) throw std::runtime_error("Unexpected trailing input bytes");
        for (auto x : h) if (x >= 22) throw std::runtime_error("Hebrew rank out of range");
        for (auto x : g) if (x >= A) throw std::runtime_error("Greek rank out of range");
        for (size_t r = 0; r < R; ++r) {
            std::array<bool,U> seen{};
            for (size_t i = 0; i < U; ++i) {
                auto k = refs[r*U+i];
                if (k >= U || seen[k]) throw std::runtime_error("Invalid reference permutation");
                seen[k] = true;
            }
        }
        size_t L = N/U;
        std::vector<Rule> rules; rules.reserve(3072);
        for (int d : directions) for (int offset : offsets) {
            std::vector<U8> q(N);
            for (size_t j = 0; j < N; ++j) {
                size_t t = uint64_t(j)*H/N;
                size_t v = ((d == 1 ? t : H-1-t) + offset) % H;
                q[j] = (22*h[v] + h[(v+1)%H]) % A;
            }
            std::vector<U32> histogram(U*U*A*A);
            for (size_t i = 0; i < U; ++i) for (size_t k = 0; k < U; ++k) {
                auto base = (i*U+k)*A*A;
                for (size_t s = 0; s < L; ++s) ++histogram[base + size_t(q[i*L+s])*A + g[k*L+s]];
            }
            for (int a : multipliers) for (int b : intercepts) {
                Rule rule{d,offset,a,b};
                for (size_t i = 0; i < U; ++i) for (size_t k = 0; k < U; ++k) {
                    U32 count = 0;
                    for (size_t x = 0; x < A; ++x) count += histogram[(i*U+k)*A*A + x*A + (a*x+b)%A];
                    if (count > L) throw std::runtime_error("Cell count exceeds unit length");
                    rule.matrix[i*U+k] = count;
                    rule.total += count;
                    if (i == k) rule.observed += count;
                }
                rule.score = I64(U)*rule.observed - rule.total;
                rules.push_back(rule);
            }
        }
        if (rules.size() != 3072) throw std::runtime_error("Wrong family cardinality");

        // Exhaustive literal check on the observed order. This bypasses both
        // the bigram/target histogram and the matrix accumulation pathway.
        size_t direct_checked = 0;
        for (const auto& r : rules) {
            I64 matches = 0;
            for (uint64_t j = 0; j < N; ++j) {
                uint64_t index = j*H/N;
                if (r.direction == -1) index = H-1-index;
                index = (index+r.offset)%H;
                auto neighbour = index+1 == H ? 0 : index+1;
                auto bigram = (22*int(h[index])+int(h[neighbour]))%24;
                matches += (r.multiplier*bigram+r.intercept)%24 == g[j];
            }
            if (matches != r.observed) throw std::runtime_error("Literal observed check failed");
            ++direct_checked;
        }
        // Summing every intercept must count each target position once.
        for (size_t first = 0; first < rules.size(); first += A) {
            I64 all_scores = 0, all_matches = 0;
            for (size_t b = 0; b < A; ++b) { all_scores += rules[first+b].score; all_matches += rules[first+b].observed; }
            if (all_scores || all_matches != N) throw std::runtime_error("Intercept conservation failed");
            for (size_t cell = 0; cell < U*U; ++cell) {
                U32 sum = 0; for (size_t b = 0; b < A; ++b) sum += rules[first+b].matrix[cell];
                if (sum != L) throw std::runtime_error("Matrix intercept conservation failed");
            }
        }
        std::string prefix(argv[2]);
        std::ofstream observed(prefix+"-rules.csv"), matrices(prefix+"-matrices.bin", std::ios::binary);
        if (!observed || !matrices) throw std::runtime_error("Cannot create outputs");
        observed << "rule_index,direction,offset,multiplier,intercept,centered_score,matches,incorrect,matrix_total\n";
        for (size_t n = 0; n < rules.size(); ++n) {
            const auto& r = rules[n];
            observed << n << ',' << r.direction << ',' << r.offset << ',' << r.multiplier << ',' << r.intercept << ',' << r.score << ',' << r.observed << ',' << N-r.observed << ',' << r.total << '\n';
            for (auto count : r.matrix) write32(matrices,count);
        }
        std::ofstream maxima(prefix+"-reference-maxima.csv");
        if (!maxima) throw std::runtime_error("Cannot create reference output");
        maxima << "reference_index,maximum_centered_score,tie_count,winning_rule_indices\n";
        I64 observed_max = std::numeric_limits<I64>::min(), exceedances = 0;
        for (const auto& r : rules) observed_max = std::max(observed_max,r.score);
        for (size_t draw = 0; draw < R; ++draw) {
            I64 best = std::numeric_limits<I64>::min(); std::vector<size_t> ties;
            for (size_t n = 0; n < rules.size(); ++n) {
                const auto& r = rules[n]; I64 matches = 0;
                for (size_t i = 0; i < U; ++i) matches += r.matrix[i*U+refs[draw*U+i]];
                I64 score = I64(U)*matches-r.total;
                if (score > best) { best = score; ties.clear(); }
                if (score == best) ties.push_back(n);
            }
            exceedances += best >= observed_max;
            maxima << draw << ',' << best << ',' << ties.size() << ',';
            for (size_t n = 0; n < ties.size(); ++n) { if (n) maxima << ';'; maxima << ties[n]; }
            maxima << '\n';
        }
        observed.close(); matrices.close(); maxima.close();
        if (!observed || !matrices || !maxima) throw std::runtime_error("Output write failed");
        double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
        std::cout << "rules=" << rules.size() << " references=" << R << " letters=" << N
                  << " direct_observed_rules_checked=" << direct_checked << " intercept_conservation=passed"
                  << " elapsed_seconds=" << elapsed << '\n';
        return 0;
    } catch (const std::exception& e) { std::cerr << "ERROR: " << e.what() << '\n'; return 1; }
}
