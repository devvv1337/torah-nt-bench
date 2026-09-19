"""Small inspectable statistical primitives; no inference of divine origin."""
import itertools
import math
import random


def confirmation_alpha(k, total=0.01):
    if not isinstance(k, int) or isinstance(k, bool) or k < 1 or not 0 < total < 1:
        raise ValueError('k must be positive and total in (0,1)')
    return total / (k * (k + 1))


def monte_carlo_p(observed, randomized):
    values = list(randomized)
    if not values or not all(math.isfinite(v) for v in [observed] + values):
        raise ValueError('Finite observed and reference scores required')
    b = sum(v >= observed for v in values)
    return (1 + b) / (1 + len(values))


def wilson(successes, n, z=1.959963984540054):
    if n < 1 or not 0 <= successes <= n:
        raise ValueError('Invalid binomial counts')
    p = successes / n
    den = 1 + z*z/n
    centre = (p + z*z/(2*n)) / den
    radius = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / den
    return [max(0.0, centre-radius), min(1.0, centre+radius)]


def score_matrix(left, right):
    if not left or len(left) != len(right) or len({len(x) for x in left + right}) != 1:
        raise ValueError('Equal number of nonempty equal-width blocks required')
    if not left[0]:
        raise ValueError('Empty blocks')
    return [[sum(a == b for a, b in zip(x, y, strict=True)) for y in right] for x in left]


def permutation_test(matrix, count, rng):
    n = len(matrix)
    if not n or any(len(row) != n for row in matrix) or count < 1:
        raise ValueError('Square matrix and positive permutation count required')
    observed = sum(matrix[i][i] for i in range(n))
    refs = []
    for _ in range(count):
        order = list(range(n)); rng.shuffle(order)
        refs.append(sum(matrix[i][j] for i, j in enumerate(order)))
    return dict(score=observed, p=monte_carlo_p(observed, refs),
                permutations=count, minimum_resolvable_p=1/(count+1))


def exact_permutation_p(matrix):
    n = len(matrix)
    if not 1 <= n <= 8 or any(len(row) != n for row in matrix):
        raise ValueError('Small square matrix required')
    obs = sum(matrix[i][i] for i in range(n))
    scores = [sum(matrix[i][j] for i, j in enumerate(p)) for p in itertools.permutations(range(n))]
    return sum(s >= obs for s in scores) / len(scores)
