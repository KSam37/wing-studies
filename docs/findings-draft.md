# Findings: draft for review

Draft of 2026-11-27, written from the live atlas (build 8e314e0).

**Setup for every number below:**
- one wing at 1 Hz, unless a frequency is given;
- 0.5 m/s forward speed;
- a −26° to +34° stroke;
- a 200 mm root chord.

Thrust is the mean per wing; torque is the peak root torque.

**Which mesh each number comes from:**
- "Coarse" means the 8 × 4 mesh the studies were searched on. Coarse numbers run about 15% low on both thrust and torque (finding 8).
- "Fine" means the 21 × 12 mesh used for the final refinement. Fine numbers run 0.5–2.4% low on thrust and 1.2–3.1% low on torque.
- "Converged" means extrapolated to zero mesh size from 21 × 12, 32 × 18 and 47 × 27, with the grid convergence index (GCI) as a 95% band (finding 8).

**Confidence:**
- **high:** the ranking or trend holds on finer meshes and across studies;
- **medium:** the result rests on the model in a regime where it is less reliable, or on limited data;
- **open:** not yet tested.

---

## 1 · Recommended wings for the FAAV build (single 400 mm sheet)

At 1 Hz:

| Torque budget | Thrust (fine) | Peak torque (fine) | Thrust (converged) | Peak torque (converged) | Half-span | Tip twist |
|---|---|---|---|---|---|---|
| 0.75 N·m | 2.26 N | 0.748 N·m | 2.30 N ± 1.1% | 0.771 N·m (+2.8% over) | 380 mm | ±54° |
| **1 N·m** | **2.73 N** | **0.999 N·m** | **2.80 N ± 1.3%** | **1.042 N·m (+4.2% over)** | **360 mm** | **±49°** |
| **1.25 N·m** | **3.11 N** | **1.250 N·m** | **3.24 N ± 2.1%** | **1.323 N·m (+5.8% over)** | **350 mm** | **±48°** |

**Where they came from.** The search was refined on the fine mesh from the best wings anywhere in the atlas.
- The 0.75 and 1 N·m wings started from plate-campaign wings.
- The 1.25 N·m wing started from the free-span study.
- At 0.75 N·m the plate-campaign start beat the free-span start by 50% (2.26 N against 1.51 N).
- At 1 N·m the two starts finished level: 2.73 N against 2.72 N, both at 360 mm. That gap is smaller than the mesh uncertainty, so either wing will do. The ♥ favourite is the earlier one.

**Shape.** All three use the full 200 mm root and taper steeply over the inner sixth of the span. The outer half is slender. The 0.75 N·m wing has a near-constant 25 mm chord along its outer two-thirds.

**Torque margin.** Each wing sits exactly on its budget on the fine mesh. Once converged, each is 3–6% over. To stay strictly within budget, either size the motor with that margin or shorten the span slightly.

**Confidence: medium.** The outlines and numbers are mesh-converged. The remaining risk is the tip twist of ±48–54°, which is large for an inviscid model (finding 9).

## 2 · Thrust against the torque budget: most of the gain comes by 1.25 N·m

Best coarse FAAV wing within one sheet, at each budget:

| Budget (N·m) | 0.5 | 0.75 | 1 | 1.25 | 1.5 | 2 |
|---|---|---|---|---|---|---|
| Thrust (N) | 1.52 | 2.27 | 2.87 | 3.06 | 3.35 | 3.42 |

- **Up to 1 N·m:** each extra 0.25 N·m buys about 0.6–0.75 N of thrust.
- **Above 1 N·m:** each extra 0.25 N·m buys about 0.2 N or less.

The reason is that the span is capped at the 400 mm sheet. Once the wing reaches that span, extra torque can only go into chord, which is less efficient.

**Confidence: high for the shape of the curve.** The individual levels are about 15% low.

## 3 · At equal torque, outline changes thrust by about a third

There are 891 verified FAAV single-sheet wings at 1 ± 0.05 N·m.

- **Spread:** thrust runs from 2.18 N to 2.93 N (+34%). The middle 80% span 2.33 N to 2.80 N (+20%).
- **Top 5% (45 wings):**
  - half-span 390–400 mm, at the sheet limit;
  - mean chords 200 · 166 · 89 · 59 · 47 · 32 · 25 · 11 mm.
- **Bottom 10%:**
  - mean half-span 321 mm;
  - broad outlines, mean chords 200 · 182 · 155 · 121 · 108 · 86 · 70 · 34 mm.

**Design rule:** spend the torque budget on span, not on outboard chord area. Use the full root, taper fast, and make the wing as long as the budget allows.

**Confidence: high.** The thrust ranking holds on finer meshes (Spearman ρ = 0.981 over 52 designs).

## 4 · The 400 mm sheet limit binds, but a joined sheet buys little

- Every top wing at 1 N·m sits at or near 400 mm.
- Allowed any span, the best coarse wing gives 3.07 N at 510 mm. That is only 7% more than the best within one sheet, and its tip twists ±69°.
- On the fine mesh, the optimized wings chose 350–380 mm at 1 Hz and 320–400 mm across frequencies. The finer mesh raises torque more for long wings, so the best span under a budget is usually below 400 mm.

**Confidence: medium.** The best span depends on the mesh.

## 5 · Passive pitching of the 0.5 mm sheet is the biggest lever, but only at the right stiffness

Best coarse wing within one sheet at ≤ 1 N·m, 1 Hz:

| Model | Thrust | Tip twist |
|---|---|---|
| **0.5 mm, pivots on a stiff leading edge (FAAV)** | **2.87 N** | ±62° |
| 0.5 mm + rod | 2.33 N | ±1° |
| 0.25 mm + rod | 2.32 N | ±2° |
| Rigid | 2.30 N | – |
| 0.25 mm, pivots freely | 2.14 N | ±63° |
| 1.0 mm, pivots freely | 2.10 N | ±5° |

- **The FAAV sheet beats a rigid wing by 25%** at the same torque.
- **There is an optimal stiffness.** Too soft (0.25 mm) or too stiff (1.0 mm) both do worse than rigid.
- **The rod removes the benefit.** Bonding the sheet to the rod stops it twisting, so the wing behaves as rigid. Rod winners re-solved as rigid plates perform about the same.

**Confidence: medium.** The benefit depends on 50–70° of passive pitch, which is where an inviscid model is least reliable (finding 9).

## 6 · Frequency is the largest single lever on thrust

Recommended FAAV single-sheet wing at each frequency and budget, refined on the fine mesh. Thrust is the converged value; brackets give the half-span.

| Budget | 0.75 Hz | 1 Hz | 1.25 Hz |
|---|---|---|---|
| 0.75 N·m | 1.65 N (380 mm) | 2.30 N (380 mm) | 2.57 N (320 mm) |
| 1 N·m | 1.92 N (340 mm) | 2.80 N (360 mm) | 3.13 N (320 mm) |
| 1.25 N·m | 2.32 N (360 mm) | 3.24 N (350 mm) | 4.52 N (400 mm) |

- **From 0.75 to 1 Hz,** thrust rises about 40% at the same torque, at every budget.
- **From 1 to 1.25 Hz,** thrust rises about 12% at 0.75 and 1 N·m, and 40% at 1.25 N·m.
- **At 1.25 Hz the wing gets shorter.** Faster flapping costs torque, so under the 0.75 and 1 N·m budgets the search pays for it with span, ending at 320 mm.
- **At 0.75 Hz the wing gets broader.** Slower flapping leaves torque to spare, so the best wings carry more chord outboard.
- **The FAAV sheet gains more from frequency than a rigid wing does.** On the coarse mesh at ≤ 1 N·m, the best rigid wing goes from 1.73 to 2.30 to 2.49 N across the three frequencies. The FAAV sheet goes from 2.14 to 2.87 to 3.58 N.

**Open questions:**
- **The jump at 1.25 Hz may be overstated.** The 1.25 Hz, 1 N·m search started 16% over budget and stopped at 320 mm. Meanwhile the 1.25 N·m wing reached 400 mm and 4.52 N. The 1 N·m search may have stopped in a local optimum. Re-running it from the 1.25 N·m wing would settle this.
- **The 1.25 Hz, 1.25 N·m wing twists ±60°,** the most of any recommended wing (finding 9).
- **Motor limits are not modelled.** Whether the motor can drive 1.25 Hz at these torques, given its power and speed limits, is outside the study.

**Confidence: high for the trend with frequency; medium for the size of the 1.25 Hz gain.** The gain rests on the same twist regime as finding 5.

## 7 · Bending along the span: small for rod builds, large for a thick free sheet, untested for the FAAV leading edge

Matched reruns compare the same wing with chordwise elasticity only and with spanwise bending added. Median changes:

| Build | Pairs | Thrust | Peak torque |
|---|---|---|---|
| 0.5 mm + rod | 66 | −2.5% | +30% |
| 0.25 mm + rod | 53 | −6.1% | −2.9% |
| 1.0 mm free sheet | 25 | −60% | −36% |
| 0.5 mm free sheet | 7 | 0% | 0% (one case −83%) |

- **Rod builds:** thrust barely changes. However, peak torque on the 0.5 mm + rod build rises 30%, so chordwise-only results understate the motor load for rod builds.
- **The FAAV build:** its leading edge is stiff by construction, which is what the chordwise model assumes. The spanwise model instead lets the sheet bend freely, so it does not describe the FAAV build directly.

**Confidence: medium for rod builds. Open for the FAAV build:** a test on the physical wing or a model with a stiff leading edge would settle it.

## 8 · The rankings are reliable; the absolute numbers are low on the coarse mesh

From 52 designs solved at several mesh and time-step levels:

| Check | Result |
|---|---|
| Design ranking kept on the fine mesh | Spearman ρ = 0.981 |
| Coarse-mesh error against the extrapolated value | median −14.6% thrust, −14.3% torque |
| Coarse-mesh error for wings longer than 450 mm | 20–38% |
| Grid convergence index for thrust, 18 × 9 mesh | median 6.8% |
| Doubling the chord panels alone | changes results 7–10% |
| Doubling the span panels alone | changes results about 5% |
| Halving the time step | changes results under 1% |

**Consequence:** a wing picked just under budget on the coarse mesh is over budget on the fine mesh. The 0.75, 1 and 1.25 N·m study picks rose 53%, 14% and 20% in torque. That is why the recommendations were re-optimized on the fine mesh (finding 1).

**The recommended wings are converged.** All nine wings in findings 1 and 6 were solved again on 32 × 18 and 47 × 27 panels:

| Check | Result |
|---|---|
| Largest change, 32 × 18 → 47 × 27 | 1.4% thrust, 1.7% torque: within the 2% stopping test |
| Converged thrust | GCI 0.6–3.1% |
| Converged torque | GCI 1.3–4.0% |
| Fine-mesh (21 × 12) values against converged | 0.5–2.4% low on thrust, 1.2–3.1% low on torque |
| Observed order of convergence | p ≈ 0.8–1.2, monotone for every wing |

Because thrust and torque rise together with the mesh, every recommended wing is 1.9–7.9% over its budget once converged. The 1.25 Hz, 1.25 N·m wing has the largest margin.

**Confidence: high.**

## 9 · Model limits: the main open risk

The method is an inviscid unsteady vortex-lattice model coupled to plate torsion.

- **Large twist.** Every high-thrust FAAV wing twists ±46–70°. At those pitch angles, flow separation and dynamic stall are likely. These effects are not modelled and would usually reduce thrust.
- **Narrow tips.** The 10 mm tip chords carry viscous drag that the model ignores.

So findings 1, 5 and 6 are the most exposed: the elastic advantage may be smaller in water than predicted.

**Status: open.** This needs an experimental check (thrust and torque on the built wing) or a higher-fidelity simulation of one recommended wing.

---

## Open items before the conclusions are final

1. Validate the large-twist regime on the built FAAV wing (findings 1, 5, 6 and 9).
2. Re-run the 1.25 Hz, 1 N·m search from the 1.25 N·m wing, to check the jump between those budgets (finding 6).
3. Check that the drive can reach 1.25 Hz at these torques (finding 6).
4. Decide whether each budget is a hard limit. If it is, shorten each recommended wing until its converged torque fits, or size the motor with a 3–8% margin (findings 1 and 8).
5. Test spanwise bending of the FAAV leading edge (finding 7).
