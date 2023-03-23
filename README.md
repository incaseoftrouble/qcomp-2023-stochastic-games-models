# qcomp-2023-stochastic-games-models

Here we collect the benchmarks for the 2023 QComp-SG comparison.

# Algorithms

## PRISM-games-extensions

Here our all configurations that I want Tobi to try out.

Command: `bin/prism <modelfile> <propertyfile> -prop <propnr> <constants> <configuration>`

Example: `./bin/prism ../../case_studies/BigMec.prism ../../case_studies/BigMec.props -prop 1 -const N=1 -ii`

Configurations (eps-optimal):
- interval iteration: `-ii`
- optimistic value iteration: `-ovi -maxiters 1`
- widest path: `-wp -maxiters 1`

Configurations (exact):
- quadratic programming: excluded since it usually is bad and requires a license for the solver
- strategy iteration: excluded since it also relies on solvers which require a license
- precise topological value iteration: excluded since all the other exact solvers are excluded
For a comparison of exact methods, we can refer to Section 6.3 in \[1\].


\[1\] Azeem, M., Evangelidis, A., Křetínský, J., Slivinskiy, A., & Weininger, M. (2022, October). Optimistic and topological value iteration for simple stochastic games. ATVA 2022. https://link.springer.com/chapter/10.1007/978-3-031-19992-9_18
