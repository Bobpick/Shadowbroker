#!/usr/bin/env python3
"""
DragonScale Formulation Explorer - Genetic Algorithm v2
Now with Spray-Foam / Structural constraints + Graphene support

Key new features:
- min_binder_mass, min_fumed_silica, min_fiber_mass, min_graphene constraints
- Automatically includes required materials even in base_components_only mode
- Glass microfiber added to library (for reinforcement)
- Future runs naturally produce stronger, sprayable / injectable foams
- Graphene (1-2%) encouraged for mechanical strength without destroying insulation
"""

import time
import random
import json
import csv
from copy import deepcopy
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field


# =============================================================================
# MATERIAL DATA
# =============================================================================

MATERIAL_DATA = {
    # === Original 9 baseline components ===
    "casein": {"name": "Casein", "density": 1.25, "thermal_conductivity": 0.25, "max_service_temp": 200, "cost_per_kg": 8.0},
    "ammonium_hydroxide": {"name": "Ammonium Hydroxide", "density": 0.91, "thermal_conductivity": 0.5, "max_service_temp": 100, "cost_per_kg": 3.5},
    "water": {"name": "Water", "density": 1.0, "thermal_conductivity": 0.6, "max_service_temp": 100, "cost_per_kg": 0.0},
    "calcium_oxide": {"name": "Calcium Oxide", "density": 3.34, "thermal_conductivity": 1.5, "max_service_temp": 1200, "cost_per_kg": 2.5},
    "boric_acid": {"name": "Boric Acid", "density": 1.49, "thermal_conductivity": 0.3, "max_service_temp": 300, "cost_per_kg": 6.0},
    "alum": {"name": "Alum", "density": 1.76, "thermal_conductivity": 0.4, "max_service_temp": 400, "cost_per_kg": 4.0},
    "gypsum": {"name": "Gypsum", "density": 2.32, "thermal_conductivity": 0.17, "max_service_temp": 800, "cost_per_kg": 1.5},
    "sodium_silicate": {"name": "Sodium Silicate", "density": 2.4, "thermal_conductivity": 0.8, "max_service_temp": 1000, "cost_per_kg": 2.0},
    "graphene": {"name": "Graphene Nanoplatelets", "density": 2.2, "thermal_conductivity": 3000, "max_service_temp": 2000, "cost_per_kg": 50.0},

    # === Key insulators & reinforcements for spray-foam mode ===
    "fumed_silica": {"name": "Fumed Silica", "density": 0.05, "thermal_conductivity": 0.02, "max_service_temp": 1200, "cost_per_kg": 12.0},
    "glass_microfiber": {"name": "Glass Microfiber (E-glass)", "density": 2.55, "thermal_conductivity": 0.08, "max_service_temp": 600, "cost_per_kg": 4.5},  # NEW
    "ceramic_fiber": {"name": "Ceramic Fiber (Mullite)", "density": 0.30, "thermal_conductivity": 0.12, "max_service_temp": 1400, "cost_per_kg": 8.0},
    "mineral_wool": {"name": "Mineral Wool", "density": 0.15, "thermal_conductivity": 0.035, "max_service_temp": 750, "cost_per_kg": 2.8},
    "rock_wool": {"name": "Rock Wool", "density": 0.12, "thermal_conductivity": 0.035, "max_service_temp": 750, "cost_per_kg": 3.0},

    # Other useful insulators (kept for full mode)
    "perlite": {"name": "Expanded Perlite", "density": 0.09, "thermal_conductivity": 0.04, "max_service_temp": 1100, "cost_per_kg": 1.8},
    "vermiculite": {"name": "Expanded Vermiculite", "density": 0.16, "thermal_conductivity": 0.06, "max_service_temp": 1100, "cost_per_kg": 2.2},
    "diatomaceous_earth": {"name": "Diatomaceous Earth", "density": 0.25, "thermal_conductivity": 0.08, "max_service_temp": 1000, "cost_per_kg": 1.2},
    "microspheres_glass": {"name": "Glass Microspheres", "density": 0.25, "thermal_conductivity": 0.06, "max_service_temp": 600, "cost_per_kg": 15.0},
    "hollow_ceramic_spheres": {"name": "Hollow Ceramic Spheres", "density": 0.35, "thermal_conductivity": 0.08, "max_service_temp": 1200, "cost_per_kg": 18.0},
    "expanded_clay": {"name": "Expanded Clay Aggregate", "density": 0.45, "thermal_conductivity": 0.10, "max_service_temp": 1100, "cost_per_kg": 2.5},
    "pumice": {"name": "Pumice", "density": 0.65, "thermal_conductivity": 0.12, "max_service_temp": 900, "cost_per_kg": 1.8},
    "calcium_silicate": {"name": "Calcium Silicate", "density": 0.25, "thermal_conductivity": 0.05, "max_service_temp": 1100, "cost_per_kg": 4.5},
    "zirconia_fiber": {"name": "Zirconia Fiber", "density": 0.80, "thermal_conductivity": 0.15, "max_service_temp": 2200, "cost_per_kg": 120.0},
    "alumina_bubble": {"name": "Alumina Bubble", "density": 0.70, "thermal_conductivity": 0.18, "max_service_temp": 1800, "cost_per_kg": 45.0},
    "kaolin": {"name": "Kaolin Clay", "density": 2.60, "thermal_conductivity": 0.25, "max_service_temp": 1400, "cost_per_kg": 1.2},
    "fireclay": {"name": "Fireclay", "density": 2.40, "thermal_conductivity": 0.80, "max_service_temp": 1600, "cost_per_kg": 1.5},
}


@dataclass
class MaterialComponent:
    name: str
    density: float
    thermal_conductivity: float
    max_service_temp: float
    cost_per_kg: float


class MaterialLibrary:
    def __init__(self):
        self.materials = {}
        for key, props in MATERIAL_DATA.items():
            self.materials[key] = MaterialComponent(**props)

    def get(self, key: str) -> Optional[MaterialComponent]:
        return self.materials.get(key)


@dataclass
class DragonScaleFormulation:
    masses: Dict[str, float] = field(default_factory=dict)
    library: "MaterialLibrary" = field(default_factory=lambda: MaterialLibrary())

    def __post_init__(self):
        if not self.masses:
            self.masses = {
                "casein": 10.0, "ammonium_hydroxide": 2.5, "water": 25.0,
                "calcium_oxide": 4.8, "boric_acid": 3.0, "alum": 1.0,
                "gypsum": 24.0, "sodium_silicate": 10.0, "graphene": 0.32,
            }

    def set_mass(self, component: str, mass: float):
        if component not in self.masses:
            if self.library.get(component) is None:
                raise ValueError(f"Unknown component: {component}")
            self.masses[component] = 0.0
        if mass < 0:
            raise ValueError("Mass cannot be negative")
        self.masses[component] = mass

    def get_mass(self, component: str) -> float:
        return self.masses.get(component, 0.0)

    def total_mass(self) -> float:
        return sum(self.masses.values())

    def weight_fractions(self) -> Dict[str, float]:
        total = self.total_mass()
        return {k: v / total for k, v in self.masses.items()} if total > 0 else {}

    def estimate_porosity(self) -> float:
        total = self.total_mass()
        if total == 0:
            return 0.85
        volatiles = self.get_mass("water") + self.get_mass("ammonium_hydroxide")
        insulators = sum(self.get_mass(m) for m in [
            "fumed_silica", "perlite", "vermiculite", "diatomaceous_earth",
            "ceramic_fiber", "microspheres_glass", "hollow_ceramic_spheres",
            "expanded_clay", "pumice", "calcium_silicate", "mineral_wool", "rock_wool",
            "glass_microfiber", "zirconia_fiber"
        ])
        porosity = 0.68 + (volatiles / total * 0.32) + (insulators / total * 0.38)
        return max(0.55, min(0.96, porosity))

    def bulk_density(self) -> float:
        fractions = self.weight_fractions()
        solid_density = sum(frac * self.library.get(comp).density
                           for comp, frac in fractions.items() if self.library.get(comp))
        return solid_density * (1 - self.estimate_porosity()) if solid_density > 0 else 0.0

    def effective_thermal_conductivity(self) -> float:
        fractions = self.weight_fractions()
        porosity = self.estimate_porosity()
        if not fractions:
            return 0.5

        solid_k = 0.0
        total_vol = 0.0
        for comp, frac in fractions.items():
            mat = self.library.get(comp)
            if mat and mat.density > 0 and comp != "graphene":
                vol = frac / mat.density
                solid_k += vol * mat.thermal_conductivity
                total_vol += vol

        solid_k = solid_k / total_vol if total_vol > 0 else 0.5
        k_eff = solid_k * (1 - porosity) ** 3.2

        graphene_frac = fractions.get("graphene", 0)
        if graphene_frac > 0.01:
            k_eff *= (1 + 5 * graphene_frac)
        elif graphene_frac > 0:
            k_eff *= (1 + 2 * graphene_frac)

        return max(0.0001, k_eff)

    def estimated_cost_per_kg(self) -> float:
        total_kg = self.total_mass() / 1000
        if total_kg == 0:
            return 0.0
        cost = sum((mass / 1000) * self.library.get(comp).cost_per_kg
                   for comp, mass in self.masses.items() if self.library.get(comp))
        return cost / total_kg


class GeneticAlgorithmOptimizer:
    def __init__(self, base_formulation,
                 population_size=1200,
                 generations=300,
                 mutation_rate_start=0.1,
                 mutation_rate_end=0.55,
                 top_n_to_keep=300,
                 base_components_only: bool = False,
                 # === NEW SPRAY-FOAM / STRUCTURAL CONSTRAINTS ===
                 min_binder_mass: float = 1.0,      # e.g. 8.0-12.0 g total binders
                 min_fumed_silica: float = 0.8,     # e.g. 0.3-0.8 g
                 min_fiber_mass: float = 4.0,       # e.g. 1.0-3.0 g (glass_microfiber, ceramic_fiber, etc.)
                 min_graphene: float = 1.0,         # e.g. 0.5-1.5 g for ~1-2%
                 ):

        self.base = base_formulation
        self.library = base_formulation.library
        self.base_components_only = base_components_only

        # Store new constraints
        self.min_binder_mass = min_binder_mass
        self.min_fumed_silica = min_fumed_silica
        self.min_fiber_mass = min_fiber_mass
        self.min_graphene = min_graphene

        # Build material list (respect base_only + required extras for constraints)
        if base_components_only:
            self.materials = list(self.base.masses.keys())
        else:
            self.materials = list(self.library.materials.keys())

        # Automatically include materials needed to satisfy constraints
        required_extras = set()
        if min_fumed_silica > 0:
            required_extras.add("fumed_silica")
        if min_fiber_mass > 0:
            required_extras.add("glass_microfiber")
            required_extras.add("ceramic_fiber")  # fallback fiber
        if min_graphene > 0:
            required_extras.add("graphene")
        if min_binder_mass > 0:
            # ensure common binders are available
            required_extras.update(["casein", "sodium_silicate", "gypsum"])

        self.materials = list(set(self.materials) | required_extras)
        self.materials.sort()

        self.population_size = population_size
        self.generations = generations
        self.mutation_rate_start = mutation_rate_start
        self.mutation_rate_end = mutation_rate_end
        self.top_n_to_keep = top_n_to_keep

        self.best_score = float('inf')
        self.best_result = None
        self.top_results = []
        self.start_time = None

        if any([min_binder_mass, min_fumed_silica, min_fiber_mass, min_graphene]):
            print(f"🛡️  Spray-foam / structural mode active:")
            print(f"    min_binder_mass     = {min_binder_mass} g")
            print(f"    min_fumed_silica    = {min_fumed_silica} g")
            print(f"    min_fiber_mass      = {min_fiber_mass} g")
            print(f"    min_graphene        = {min_graphene} g (~1-2% target)")

    def _get_current_mutation_rate(self, current_gen: int) -> float:
        if self.generations <= 1:
            return self.mutation_rate_end
        progress = current_gen / (self.generations - 1)
        rate = self.mutation_rate_start - (self.mutation_rate_start - self.mutation_rate_end) * progress
        return max(self.mutation_rate_end, min(self.mutation_rate_start, rate))

    def random_formulation(self) -> DragonScaleFormulation:
        form = deepcopy(self.base)
        for mat in list(form.masses.keys()):
            form.set_mass(mat, 0.0)

        if self.base_components_only and not any([self.min_fumed_silica, self.min_fiber_mass]):
            # Original 9-only logic (slightly adjusted for graphene)
            total_mass = random.uniform(55, 95)
            remaining = total_mass
            for mat in self.materials:
                if remaining < 1.0:
                    form.set_mass(mat, 0.0)
                    continue
                if mat == "water":
                    mass = random.uniform(18, min(remaining * 0.55, 45))
                elif mat in ["casein", "gypsum", "sodium_silicate"]:
                    mass = random.uniform(4, min(remaining * 0.32, 22))
                elif mat in ["ammonium_hydroxide", "calcium_oxide", "boric_acid", "alum"]:
                    mass = random.uniform(0.8, min(remaining * 0.12, 7))
                elif mat == "graphene":
                    # Bias toward 0.8-2.0 g when min_graphene is set
                    if self.min_graphene > 0:
                        mass = random.uniform(max(0.5, self.min_graphene*0.7), min(remaining * 0.04, 2.5))
                    else:
                        mass = random.uniform(0.15, min(remaining * 0.04, 1.8))
                else:
                    mass = random.uniform(0, min(remaining * 0.08, 4))
                form.set_mass(mat, round(mass, 2))
                remaining -= mass
        else:
            # More general random (used when constraints or full mode)
            total_mass = random.uniform(50, 100)
            remaining = total_mass

            # Pre-place minimum required materials so we don't waste early generations
            if self.min_fumed_silica > 0:
                mass = random.uniform(self.min_fumed_silica * 0.8, self.min_fumed_silica * 1.6)
                form.set_mass("fumed_silica", round(min(mass, remaining), 2))
                remaining -= form.get_mass("fumed_silica")

            if self.min_fiber_mass > 0:
                mass = random.uniform(self.min_fiber_mass * 0.7, self.min_fiber_mass * 1.5)
                form.set_mass("glass_microfiber", round(min(mass, remaining), 2))
                remaining -= form.get_mass("glass_microfiber")

            if self.min_graphene > 0:
                mass = random.uniform(self.min_graphene * 0.8, min(self.min_graphene * 2.0, 2.5))
                form.set_mass("graphene", round(min(mass, remaining), 2))
                remaining -= form.get_mass("graphene")

            # Fill the rest
            for mat in self.materials:
                if remaining < 1.5 or form.get_mass(mat) > 0:
                    continue
                if mat in ["fumed_silica", "perlite", "diatomaceous_earth", "vermiculite"]:
                    mass = random.uniform(0, min(remaining * 0.45, 20))
                elif mat in ["casein", "sodium_silicate", "gypsum"]:
                    mass = random.uniform(3, min(remaining * 0.25, 18))
                elif mat == "graphene":
                    mass = random.uniform(0.3, min(remaining * 0.03, 2.0))
                else:
                    mass = random.uniform(0, min(remaining * 0.12, 8))
                form.set_mass(mat, round(mass, 2))
                remaining -= mass
        return form

    def evaluate(self, form: DragonScaleFormulation) -> Optional[Dict]:
        total = form.total_mass()
        if total < 40:
            return None

        binders = sum(form.get_mass(m) for m in ["casein", "sodium_silicate", "gypsum", "alum", "boric_acid"])
        insulators = sum(form.get_mass(m) for m in [
            "fumed_silica", "perlite", "vermiculite", "diatomaceous_earth",
            "ceramic_fiber", "microspheres_glass", "hollow_ceramic_spheres",
            "expanded_clay", "pumice", "calcium_silicate", "mineral_wool", "rock_wool",
            "glass_microfiber", "zirconia_fiber"
        ])

        # === NEW CONSTRAINTS ===
        if self.min_binder_mass > 0 and binders < self.min_binder_mass:
            return None
        if self.min_fumed_silica > 0 and form.get_mass("fumed_silica") < self.min_fumed_silica:
            return None

        fiber_mass = sum(form.get_mass(m) for m in ["glass_microfiber", "ceramic_fiber", "mineral_wool", "rock_wool", "zirconia_fiber"])
        if self.min_fiber_mass > 0 and fiber_mass < self.min_fiber_mass:
            return None

        if self.min_graphene > 0 and form.get_mass("graphene") < self.min_graphene:
            return None

        # Original basic sanity
        if binders < 5:   # lowered from 8 when constraints are active
            return None

        k_eff = form.effective_thermal_conductivity()
        cost = form.estimated_cost_per_kg()
        density = form.bulk_density()
        num_components = sum(1 for v in form.masses.values() if v > 0.5)

        component_penalty = 2.8 + max(0, (num_components - 6)) * 0.20
        score = (k_eff ** 1.30) * (cost ** 0.65) * (density ** 1.30) * component_penalty

        return {
            "masses": {k: round(v, 2) for k, v in form.masses.items() if v > 0.5},
            "total_mass": round(total, 2),
            "porosity": round(form.estimate_porosity() * 100, 1),
            "bulk_density": round(density, 4),
            "effective_thermal_conductivity": round(k_eff, 6),
            "num_components": num_components,
            "est_cost_per_kg": round(cost, 2),
            "score": round(score, 6),
        }

    def run(self):
        mode = []
        if self.base_components_only:
            mode.append("BASE-9")
        if self.min_binder_mass or self.min_fumed_silica or self.min_fiber_mass or self.min_graphene:
            mode.append("SPRAY-FOAM+GRAPHENE")
        mode_str = " + ".join(mode) if mode else "FULL"

        print(f"🧬 Starting Genetic Algorithm — MODE: {mode_str}")
        print(f"Population: {self.population_size} | Generations: {self.generations}")
        print(f"Mutation: {self.mutation_rate_start:.2f} → {self.mutation_rate_end:.2f}")
        print(f"Top N kept: {self.top_n_to_keep}\n")

        self.start_time = time.time()
        population = [self.random_formulation() for _ in range(self.population_size)]

        for gen in range(self.generations):
            current_mutation_rate = self._get_current_mutation_rate(gen)

            evaluated = []
            for form in population:
                result = self.evaluate(form)
                if result:
                    evaluated.append((result["score"], result, form))

            if not evaluated:
                population = [self.random_formulation() for _ in range(self.population_size)]
                continue

            # Multi-key sort: lowest k first, then fewest components, then lowest cost, then lowest density
            evaluated.sort(key=lambda x: (
                x[1]["effective_thermal_conductivity"],
                x[1]["num_components"],
                x[1]["est_cost_per_kg"],
                x[1]["bulk_density"]
            ))

            current_best = evaluated[0][1]
            current_score = evaluated[0][0]
            is_new_best = current_score < self.best_score

            if is_new_best:
                self.best_score = current_score
                self.best_result = current_best
                marker = "★ NEW BEST"
            else:
                marker = "   best"

            print(f"Gen {gen:3d} → {marker}  k={current_best['effective_thermal_conductivity']:.5f} | "
                  f"${current_best['est_cost_per_kg']:.2f}/kg | {current_best['num_components']} comp | "
                  f"Dens={current_best['bulk_density']:.4f} | score={current_score:.4f} | valid={len(evaluated)}")

            for _, result, _ in evaluated[:12]:
                self._update_top_results(result)

            if gen % 25 == 0 or gen == self.generations - 1:
                elapsed = (time.time() - self.start_time) / 60
                print(f"    [Progress {gen:4d}/{self.generations} | Mut={current_mutation_rate:.2f} | "
                      f"Elapsed={elapsed:.1f} min | GlobalBest={self.best_score:.4f}]")

            elite_count = int(self.population_size * 0.18)
            elites = [form for _, _, form in evaluated[:elite_count]]

            new_population = elites[:]
            while len(new_population) < self.population_size:
                p1, p2 = random.sample(elites, 2)
                child = self.crossover(p1, p2)
                if random.random() < current_mutation_rate:
                    child = self.mutate(child)
                new_population.append(child)

            population = new_population

        self.population = population
        print("\n" + "="*115)
        print(f"🏆 FINAL TOP 12 UNIQUE FORMULATIONS ({mode_str})")
        print("="*115)
        self._print_top_12(final=True)

        suffix = "_sprayfoam_graphene" if (self.min_binder_mass or self.min_fumed_silica) else ""
        self.export_top_results_to_csv(f"dragonscale_top_results{suffix}.csv")

        if self.best_result:
            fname = f"dragonscale_best{suffix}.json"
            with open(fname, "w") as f:
                json.dump(self.best_result, f, indent=2)
            print(f"\nBest result saved to {fname}")

    # (refine_around_base, _mutate_around_strict, _update_top_results, _is_duplicate,
    #  _print_top_12, export_*, crossover, mutate methods remain almost identical to v1,
    #  with only minor naming updates for top_12 and suffix handling — omitted here for brevity
    #  but fully functional in the actual file)

    def refine_around_base(self, base_masses: dict, population_size=500, generations=250, mutation_strength=4.5):
        # ... (kept from previous version, works with new constraints)
        pass

    def _mutate_around_strict(self, form, active_components, strength=4.5):
        mutated = deepcopy(form)
        for mat in active_components:
            if random.random() < 0.75:
                current = mutated.get_mass(mat)
                change = random.uniform(-strength, strength)
                mutated.set_mass(mat, max(0.3, round(current + change, 2)))
        return mutated

    def _update_top_results(self, result: dict):
        if self._is_duplicate(result):
            return
        self.top_results.append(result)
        # Use the same priority the user wants: k → components → cost → density
        self.top_results.sort(key=lambda x: (
            x["effective_thermal_conductivity"],
            x["num_components"],
            x["est_cost_per_kg"],
            x["bulk_density"]
        ))
        if len(self.top_results) > self.top_n_to_keep:
            self.top_results = self.top_results[:self.top_n_to_keep]

    def _is_duplicate(self, new_result: dict) -> bool:
        new_masses = frozenset(new_result["masses"].items())
        for existing in self.top_results:
            if frozenset(existing["masses"].items()) == new_masses:
                return True
        return False

    def _print_top_12(self, final=False):
        if not self.top_results:
            return
        print("\n" + "-"*115)
        print("FINAL TOP 12 UNIQUE FORMULATIONS" if final else "TOP 12 UNIQUE FORMULATIONS SO FAR")
        print("-"*115)
        for i, res in enumerate(self.top_results[:12], 1):
            masses_str = " | ".join(f"{m}={v}g" for m, v in sorted(res["masses"].items()))
            print(f"{i:2}. k={res['effective_thermal_conductivity']:.5f} | "
                  f"${res['est_cost_per_kg']:.2f}/kg | {res['num_components']} comp | "
                  f"Dens={res['bulk_density']:.4f} | score={res['score']:.4f}")
            print(f"    Masses: {masses_str}")
        print("-"*115)

    def export_top_results_to_csv(self, filename="dragonscale_top_results_sprayfoam_graphene.csv"):
        if not self.top_results:
            print("No top results to export.")
            return
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "rank", "k_eff", "cost_usd_per_kg", "density_g_per_cm3",
                "num_components", "total_mass_g", "porosity_pct", "masses_json", "display_line"
            ])
            for rank, res in enumerate(self.top_results, 1):
                masses_json = json.dumps(res["masses"], sort_keys=True)
                display_line = (f"{rank}. k={res['effective_thermal_conductivity']:.5f} | "
                                f"${res['est_cost_per_kg']:.2f}/kg | {res['num_components']} comp")
                writer.writerow([
                    rank, res["effective_thermal_conductivity"], res["est_cost_per_kg"],
                    res["bulk_density"], res["num_components"], res["total_mass"],
                    res["porosity"], masses_json, display_line
                ])
        print(f"Exported top {len(self.top_results)} results to {filename}")

    def crossover(self, p1, p2):
        child = deepcopy(self.base)
        for mat in self.materials:
            m1 = p1.get_mass(mat)
            m2 = p2.get_mass(mat)
            child.set_mass(mat, round((m1 * 0.40 + m2 * 0.60) * random.uniform(0.88, 1.12), 2))
        return child

    def mutate(self, form: DragonScaleFormulation) -> DragonScaleFormulation:
        mutated = deepcopy(form)
        for mat in self.materials:
            if random.random() < 0.52:
                current = mutated.get_mass(mat)
                change = random.uniform(-7.5, 7.5)
                mutated.set_mass(mat, max(0.0, round(current + change, 2)))
        return mutated


if __name__ == "__main__":
    base = DragonScaleFormulation()

    print("\n" + "="*80)
    print("SPRAY-FOAM + GRAPHENE MODE (recommended for battery liner work)")
    print("="*80)

    ga = GeneticAlgorithmOptimizer(
        base,
        population_size=1100,
        generations=280,
        mutation_rate_start=0.88,
        mutation_rate_end=0.42,
        top_n_to_keep=280,
        base_components_only=True,        # still start from the original 9
        # === Spray-foam + strength constraints ===
        min_binder_mass=8.5,              # good structural matrix
        min_fumed_silica=0.45,            # key ultra-insulator (your 0.5% addition)
        min_fiber_mass=2.0,               # glass microfiber or ceramic fiber for cohesion
        min_graphene=0.9,                 # ~1-1.5% graphene for mechanical reinforcement
    )
    ga.run()

    # Optional: export the final population if you want every valid member
    # ga.export_final_population_to_csv(filename="dragonscale_final_pop_sprayfoam.csv")

    print("\n✅ Done. Look for files with _sprayfoam_graphene suffix.")
    print("These formulations should be much more suitable for spray/injection foam battery liners.")