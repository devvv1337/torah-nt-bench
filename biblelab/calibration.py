"""A deliberately limited detector diagnostic on non-target texts and injected copies."""
import json
import math
import random
from .letters import HEBREW, GREEK, HEBREW_FINAL
from .sources import ROOT, verify, digest, write_json
from .registry import append, snapshot_code
from .statistics import score_matrix, permutation_test, wilson


def blockify(values, blocks, width):
    if len(values) < blocks * width:
        raise ValueError('Insufficient continuous control prefix')
    return [values[i*width:(i+1)*width] for i in range(blocks)]


def binomial_upper(k, n, p):
    return sum(math.comb(n, i) * p**i * (1-p)**(n-i) for i in range(k, n+1))


def run(root=ROOT):
    verify(root)
    protocol_path = root / 'protocol/calibration-v1.json'
    spec = json.loads(protocol_path.read_text())
    data_path = root / 'data/derived/controls.json'
    # Re-derive all controls from verified raw inputs instead of trusting a mutable cache.
    from .editions import controls
    controls(root)
    controls_data = json.loads(data_path.read_text())
    snapshot = snapshot_code(root)
    start = append(root / 'registry/events.jsonl', 'calibration_started', {
        'id': spec['id'], 'spec_sha256': digest(protocol_path.read_bytes()),
        'code_snapshot': snapshot, 'controls_sha256': digest(data_path.read_bytes()),
        'uses_target_corpora': False, 'confirmatory_candidate': False})
    rng = random.Random(spec['seed'])
    n, w, B = spec['blocks'], spec['width'], spec['permutations']
    alpha = spec['diagnostic_alpha']
    left_stream = controls_data['berakhot']['letters'].translate(HEBREW_FINAL)
    right_stream = controls_data['xenophon']['contiguous_prefix_letters']
    left = blockify([HEBREW.index(c) for c in left_stream], n, w)
    right = blockify([GREEK.index(c) for c in right_stream], n, w)
    base = score_matrix(left, right)
    descriptive = permutation_test(base, B, rng)
    null_trials = []
    for _ in range(spec['null_repetitions']):
        order = list(range(n)); rng.shuffle(order)
        matrix = [[row[j] for j in order] for row in base]
        null_trials.append(permutation_test(matrix, B, rng))
    rejected = sum(t['p'] <= alpha for t in null_trials)
    tail = binomial_upper(rejected, len(null_trials), alpha)
    powers, power_trials = [], []
    for rate in spec['noise_rates']:
        results = []
        for _ in range(spec['power_repetitions']):
            # The encoded Greek sequence has the same ordered alphabet ranks by construction.
            altered = [[rng.randrange(len(HEBREW)) if rng.random() < rate else c for c in block] for block in left]
            results.append(permutation_test(score_matrix(left, altered), B, rng))
        k = sum(t['p'] <= alpha for t in results)
        powers.append(dict(noise=rate, detections=k, repetitions=len(results),
                           fraction=k/len(results), wilson95=wilson(k, len(results))))
        power_trials.append(dict(noise=rate, trials=results))
    report = dict(
        protocol=spec, protocol_sha256=digest(protocol_path.read_bytes()),
        started_event_sha256=start['sha256'],
        human_control_pair=descriptive,
        null_diagnostic=dict(rejections=rejected, repetitions=len(null_trials), fraction=rejected/len(null_trials),
                             wilson95=wilson(rejected, len(null_trials)), binomial_upper_p=tail,
                             fpr_alarm=tail < 0.01),
        sensitivity=powers,
        calibration_gate_pass=(tail >= 0.01 and powers[0]['fraction'] >= spec['minimum_exact_signal_detection_fraction']),
        trials=dict(null=null_trials, injected=power_trials),
        target_cross_corpus_tests=0,
        limitation='Valid only under declared block-order randomization; natural texts need not be exchangeable. This validates one primitive, not the ultimate instrument.',
    )
    write_json(root / 'reports/calibration-v1.json', report)
    sha = digest((root / 'reports/calibration-v1.json').read_bytes())
    write_json(root / f'reports/archive/calibration-v1.{sha[:12]}.json', report)
    append(root / 'registry/events.jsonl', 'calibration_finished', {
        'id':spec['id'], 'report_sha256':sha, 'gate_pass':report['calibration_gate_pass'],
        'is_target_discovery':False})
    return {k:v for k,v in report.items() if k not in ('trials','protocol')}
