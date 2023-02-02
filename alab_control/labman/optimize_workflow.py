from ortools.linear_solver import pywraplp
from .components import InputFile
from typing import Dict, List, Tuple


class BatchOptimizer:
    def __init__(
        self,
        available_quadrants: List[int],
        available_powders: Dict[str, float],
        available_crucibles: List[List[int]],
        available_jars: List[List[int]],
        inputfiles: List[InputFile],
    ):
        """Provide an optimal workflow that maximizes use of available powder, jars, and crucibles on unoccupied quadrants

        Args:
            available_quadrants (List[int]): indices [1,2,3, or 4] of available quadrants
            available_powders (Dict[str, float]): dictionary of available powders and their masses {powder_name: mass_g}
            available_crucibles (List[int]): indices of available jars per quadrant index in available_quadrants
            available_jars (List[int]): indices of available jars per quadrant index in available_quadrants
            inputfiles (List[InputFile]): list of candidate inputfiles to be packed into a workflow

        Raises:
            Exception: TODO
        """
        self.quadrant_indices = available_quadrants
        if (
            not len(self.quadrant_indices)
            == len(available_crucibles)
            == len(available_jars)
        ):
            raise Exception(
                "Mismatch between number of quadrants and number of crucibles/jars!"
            )
        self.powders = list(available_powders.keys())
        self.powder_masses = list(available_powders.values())
        self.crucibles = available_crucibles
        self.jars = available_jars

        self.inputfiles = []
        self.inputfile_indices = []
        self.requested_masses = []
        self.requested_crucibles = []
        self.requested_jars = []
        for i, inp in enumerate(inputfiles):
            if any([p not in self.powders for p in inp.powder_dispenses.keys()]):
                continue  # this powder is not available in Labman rn
            self.inputfiles.append(inp)
            self.inputfile_indices.append(i)
            self.requested_masses.append(
                [inp.powder_dispenses.get(p, 0) for p in self.powders]
            )
            self.requested_crucibles.append(inp.replicates)
            self.requested_jars.append(1)

        ages = [inp.age for inp in self.inputfiles]

        def age_to_weight(
            age,
            min_age: float,
            max_age: float,
            min_weight: float = 1,
            max_weight: float = 1.5,
        ) -> float:
            """Give a higher weight to older inputfiles.
                Normalizes the relative age of an inputfile to be between min_weight and max_weight.
                This will be used to prioritize older inputfiles in the optimization.
                A greater value for max_weight will prioritize older inputfiles more.

                For example, with min_weight=1 and max_weight=1.5, the oldest inputfile will be worth 1.5 of the youngest inputfile.

            Args:
                age (float): age of the inputfile to be weighted, arbitrary units. Usually seconds.
                min_age (float): minimum age of all inputfiles
                max_age (float): maximum age of all inputfiles
                min_weight (float, optional): minimum weight. Defaults to 1.
                max_weight (float, optional): maximum weight. Defaults to 1.5.
            Returns:
                float: the factor by which to weight the value of adding this inputfile to a workflow.
            """
            if max_age == min_age:
                return 1
            if max_age < min_age:
                min_age, max_age = max_age, min_age
            return min_weight + (max_weight - min_weight) * (age - min_age) / (
                max_age - min_age
            )

        self.inputfile_weights = [
            age_to_weight(age, min(ages), max(ages)) for age in ages
        ]

    def solve_for_one_quadrant(
        self, quadrant_index: int, verbose: bool = False
    ) -> Tuple[int, List[InputFile]]:
        if quadrant_index not in self.quadrant_indices:
            raise Exception("Invalid quadrant index!")
        solver: pywraplp.Solver = pywraplp.Solver.CreateSolver("SCIP")
        available_crucibles = len(
            self.crucibles[self.quadrant_indices.index(quadrant_index)]
        )
        available_jars = len(self.jars[self.quadrant_indices.index(quadrant_index)])
        if not solver:
            return

        # Variables
        # x[i] = 1 if inputfile i is loaded into this workflow
        x = [solver.IntVar(0, 1, f"{i}_loaded") for i in self.inputfile_indices]

        # total mass requested of each powder must be less than or equal to the available mass
        mass_required_solver_vars = []
        for col, _ in enumerate(self.powders):
            mass_required_of_this_powder = solver.Sum(
                [
                    masses_for_this_inputfile[col] * inputfile_is_included
                    for masses_for_this_inputfile, inputfile_is_included in zip(
                        self.requested_masses, x
                    )
                ]
            )
            mass_required_solver_vars.append(mass_required_of_this_powder)
            solver.Add(mass_required_of_this_powder <= self.powder_masses[col])

        # total crucibles requested must be less than or equal to the available crucibles
        n_crucibles_used = solver.Sum(
            [
                inputfile_is_included * n_crucibles_for_this_inputfile
                for n_crucibles_for_this_inputfile, inputfile_is_included in zip(
                    self.requested_crucibles, x
                )
            ]
        )
        solver.Add(n_crucibles_used <= available_crucibles, "crucible_limit")

        # total jars requested must be less than or equal to the available jars
        n_jars_used = solver.Sum(
            [
                inputfile_is_loaded * n_jars_for_this_inputfile
                for n_jars_for_this_inputfile, inputfile_is_loaded in zip(
                    self.requested_jars, x
                )
            ]
        )
        solver.Add(n_jars_used <= available_jars, "jar_limit")

        # Objectives
        weighted_values = [
            weight * inputfile_is_included
            for weight, inputfile_is_included in zip(self.inputfile_weights, x)
        ]
        num_inputfiles = solver.Sum(weighted_values)
        solver.Maximize(num_inputfiles)
        status = solver.Solve()

        if status == pywraplp.Solver.OPTIMAL:
            crucible_utilization = (
                n_crucibles_used.solution_value() / available_crucibles
            )
            jar_utilization = n_jars_used.solution_value() / available_jars
            num_inputfiles = round(solver.Objective().Value())
            powder_utilization = {
                self.powders[i]: mass_required_solver_vars[i].solution_value()
                / self.powder_masses[i]
                for i in range(len(self.powders))
            }
            n_powders_used = len([v for v in powder_utilization.values() if v > 0])
            if verbose:
                print(f"Optimal solution found for quadrant {quadrant_index}")
                print("Number of inputfiles loaded:", num_inputfiles)
                print("Crucible utilization:", crucible_utilization)
                print("Jar utilization:", jar_utilization)
                print("Number of powders used:", n_powders_used)
                print("Powder utilization:", powder_utilization)
            return {
                "quadrant": quadrant_index,
                "inputfiles": [
                    self.inputfiles[i]
                    for i in self.inputfile_indices
                    if x[i].solution_value() == 1
                ],
                "num_inputfiles": num_inputfiles,
                "crucible_utilization": crucible_utilization,
                "jar_utilization": jar_utilization,
                "n_powders_used": n_powders_used,
                "powder_utilization": powder_utilization,
            }

        else:
            print("No optimal solution found.")
            return None

    def solve(self, verbose: bool = False):
        """Attempts to bin-pack the inputfiles into the available crucibles and jars on each quadrant. Returns the largest possible set on inputfiles, and says which quadrant to run them

        Args:
            verbose (bool, optional): Whether to print out the results of binpacking per quadrant. Defaults to False.

        Raises:
            Exception: Binpacking is unsuccessful for all quadrants, no solution found.

        Returns:
            Tuple[int, List[InputFile]]: Index of quadrant to run, and list of InputFiles to run on the quadrant.

        """
        best = None
        for q in self.quadrant_indices:
            results = self.solve_for_one_quadrant(q, verbose=verbose)
            if verbose and q != self.quadrant_indices[-1]:
                print("================")
            if results is None:
                continue
            if best is None:
                best = results
            if results["num_inputfiles"] > best["num_inputfiles"]:
                best = results
            elif results["num_inputfiles"] == best["num_inputfiles"]:
                if (results["crucible_utilization"] + results["jar_utilization"]) > (
                    best["crucible_utilization"] + best["jar_utilization"]
                ):
                    best = results

        if best is None:
            raise Exception("No solution could be found!")
        return best["quadrant"], best["inputfiles"]
