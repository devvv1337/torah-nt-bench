// Reproduce saved reference inputs from the declared seed, without any scoring.
// The production RNG is deliberately shared; this is a provenance check,
// not an algorithmically independent random generator or a scientific replicate.
#define BIBLELAB_CONTEXTUAL_MATCH_NO_MAIN
#include "contextual_match.cpp"
#undef BIBLELAB_CONTEXTUAL_MATCH_NO_MAIN

int main(int argc,char **argv) {
    try {
        if(argc!=5)throw std::runtime_error("usage: reference_replay INPUT OUTPUT_PREFIX DRAWS SEED");
        if(std::string(argv[3]).find_first_not_of("0123456789")!=std::string::npos||
            std::string(argv[4]).find_first_not_of("0123456789")!=std::string::npos)
            throw std::runtime_error("Replay count and seed must be nonnegative decimal integers");
        std::size_t count_end=0,seed_end=0;
        const auto draws=std::stoull(argv[3],&count_end),seed=std::stoull(argv[4],&seed_end);
        if(count_end!=std::string(argv[3]).size()||seed_end!=std::string(argv[4]).size()||draws<1||draws>40000)
            throw std::runtime_error("Invalid replay count or seed");
        std::ifstream in(argv[1]);int nl,nr;
        if(!(in>>nl>>nr)||nl<0||nr<0)throw std::runtime_error("Invalid replay dimensions");
        std::string line;std::getline(in,line);
        auto left=context_read(in,nl),right=context_read(in,nr);
        std::mt19937_64 rng(seed);
        for(int mode=0;mode<2;++mode)for(std::uint64_t i=0;i<draws;++i) {
            ContextUnits ref;
            if(mode==0){ref=right;ref.units=randomized(right.units,1,rng);}else ref=context_types(right,rng);
            const auto prefix=std::string(argv[2])+(mode==0?"words.":"word_types.");
            if(i==0)context_save(prefix+"first.txt",left,ref);
            if(i==draws-1)context_save(prefix+"last.txt",left,ref);
        }
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
