from typing import Tuple

import numpy as np
import yaml
import os

from . import transform_utils as T
from .furniture_sawyer import FurnitureSawyerEnv
from .models import furniture_name2id
from ..util.logger import logger


class FurnitureSawyerDenseRewardEnv(FurnitureSawyerEnv):
    """
    Sawyer environment.
    Here, we call a moving object as 'leg' and a target object as 'table'.
    """

    def __init__(self, config):
        """
        Args:
            config: configurations for the environment.
        """
        config.furniture_id = furniture_name2id[config.furniture_name]
        super().__init__(config)

        self._diff_rew = config.diff_rew
        self._phase_bonus = config.phase_bonus
        self._ctrl_penalty_coef = config.ctrl_penalty_coef
        self._pos_threshold = config.pos_threshold
        self._rot_threshold = config.rot_threshold
        self._eef_rot_dist_coef = config.eef_rot_dist_coef
        self._eef_up_rot_dist_coef = config.eef_up_rot_dist_coef
        self._eef_pos_dist_coef = config.eef_pos_dist_coef
        self._lower_eef_pos_dist_coef = config.lower_eef_pos_dist_coef
        self._lift_dist_coef = config.lift_dist_coef
        self._grasp_dist_coef = config.grasp_dist_coef
        self._gripper_penalty_coef = config.gripper_penalty_coef
        self._align_pos_dist_coef = config.align_pos_dist_coef
        self._align_rot_dist_coef = config.align_rot_dist_coef
        self._align_pos_threshold = config.align_pos_threshold
        self._align_rot_threshold = config.align_rot_threshold
        self._move_pos_dist_coef = config.move_pos_dist_coef
        self._move_rot_dist_coef = config.move_rot_dist_coef
        self._move_pos_threshold = config.move_pos_threshold
        self._move_rot_threshold = config.move_rot_threshold
        self._move_fine_rot_dist_coef = config.move_fine_rot_dist_coef
        self._move_fine_pos_dist_coef = config.move_fine_pos_dist_coef
        self._touch_coef = config.touch_coef
        self._aligned_bonus_coef = config.aligned_bonus_coef
        self._move_other_part_penalty_coef = config.move_other_part_penalty_coef

        self._num_connect_steps = 0
        self._grip_open_phases = set(["move_eef_above_leg", "lower_eef_to_leg"])
        self._phases = [
            "move_eef_above_leg",
            "lower_eef_to_leg",
            "grasp_leg",
            "lift_leg",
            "align_leg",
            "move_leg",
            "move_leg_fine",
        ]

    def _reset_reward_variables(self):
        self._subtask_step = len(self._preassembled)
        self._update_reward_variables(self._subtask_step)

    def _set_next_subtask(self) -> bool:
        """Returns True if we are done with all attaching steps"""
        self._subtask_step += 1
        if self._subtask_step == self._success_num_conn:
            return True
        self._update_reward_variables(self._subtask_step)
        return False

    def _update_reward_variables(self, subtask_step):
        """Updates the reward variables wrt subtask step"""
        self._phase_i = 0
        self._leg, self._table = self._recipe["recipe"][subtask_step]
        self._leg_site, self._table_site = self._site_recipe[subtask_step][:2]
        if len(self._site_recipe[subtask_step]) == 3:
            self._table_leg_angle = self._site_recipe[subtask_step][2]
        else:
            self._table_leg_angle = None
        # update the observation to the current objects of interest
        self._subtask_part1 = self._object_name2id[self._leg]
        self._subtask_part2 = self._object_name2id[self._table]
        self._leg_touched = False
        self._leg_lift = False
        self._init_table_site_pos = self._get_pos(self._table_site)
        self._init_lift_leg_pos = leg_pos = self._get_pos(self._leg)
        self._lift_leg_pos = leg_pos + [0, 0, 0.2]
        self._leg_fine_aligned = 0
        self._leg_allowed_angles = [x for x in self._leg_site.split(",")[1:-1] if x]

        g1, g2 = f"{self._leg}_ltgt_site0", f"{self._leg}_rtgt_site0"
        if "grip_site_recipe" in self._recipe and self._subtask_step < len(
            self._recipe["grip_site_recipe"]
        ):
            g1, g2 = self._recipe["grip_site_recipe"][self._subtask_step]
        self._get_leg_grasp_pos = lambda x: (self._get_pos(g1) + self._get_pos(g2)) / 2
        self._get_leg_grasp_vector = lambda x: self._get_pos(g2) - self._get_pos(g1)

        if self._diff_rew:
            eef_pos = self._get_pos("griptip_site")
            leg_pos = self._get_leg_grasp_pos(self._leg)  # + [0, 0, 0.07]
            leg_pos[2] = 0.08
            xy_dist = np.linalg.norm(eef_pos[:2] - leg_pos[:2])
            z_dist = np.abs(eef_pos[2] - leg_pos[2])
            self._prev_eef_above_leg_dist = xy_dist + z_dist
            self._prev_grasp_dist = -1
            self._prev_lift_leg_z_dist = 0.2
            self._prev_lift_leg_xy_dist = 0.0

    def _reset(self, furniture_id=None, background=None):
        super()._reset(furniture_id, background)
        self._reset_reward_variables()

    def _step(self, a):
        """
        Takes a simulation step with @a and computes reward.
        """

        ob, reward, done, info = super()._step(a)
        return ob, reward, done, info

    def _collect_values(self):
        """ Collects all sensor values required for reward. """

        left, right = self._finger_contact(self._leg)
        leg_up = self._get_up_vector(self._leg_site)
        table_up = self._get_up_vector(self._table_site)
        leg_forward = self._get_forward_vector(self._leg_site)
        if len(self._leg_allowed_angles):
            target_forward = self._project_connector_forward(
                self._table_site, self._leg_site, self._table_leg_angle
            )
        else:
            target_forward = leg_forward
        leg_site_pos = self._get_pos(self._leg_site)
        leg_pos = self._get_pos(self._leg)
        table_site_pos = self._get_pos(self._table_site)
        above_table_site_pos = table_site_pos + [
            0,
            0,
            self._recipe["z_finedist"],
        ]

        self._current_values = {
            "left": left,
            "right": right,
            "leg_touched": int(left and right),
            "leg_pos": leg_pos,
            "lift": leg_pos[2] > self._lift_leg_pos[2],
            "leg_site_pos": leg_site_pos,
            "table_site_pos": table_site_pos,
            "above_table_site_pos": above_table_site_pos,
            "move_pos_dist": np.linalg.norm(table_site_pos - leg_site_pos),
            "move_above_pos_dist": np.linalg.norm(above_table_site_pos - leg_site_pos),
            "leg_up": leg_up,
            "table_up": table_up,
            "move_ang_dist": T.cos_siml(leg_up, table_up),
            "leg_forward": leg_forward,
            "target_forward": target_forward,
            "move_forward_ang_dist": T.cos_siml(leg_forward, target_forward),
            "proj_table": T.cos_siml(-table_up, leg_site_pos - table_site_pos),
            "proj_leg": T.cos_siml(leg_up, table_site_pos - leg_site_pos),
            "table_displacement": np.linalg.norm(
                table_site_pos - self._init_table_site_pos
            ),
        }

    def _compute_reward(self, ac) -> Tuple[float, bool, dict]:
        """
        Computes multi-phase reward.
        While moving the leg, we need to make sure the grip is stable by measuring
        angular movements.
        At any point, the robot should minimize pose displacement in non-relevant parts.

        Phases:
        - move_eef_above_leg: move eef over table leg
        - lower_eef_to_leg: lower eef onto the leg
        - grasp_leg: grip the leg
        - lift_leg: lift the leg to specified height
        - align_leg: align the rotation of the leg with the target conn site
        - move_leg: coarsely align the leg with the conn site
        - move_leg_fine: fine grain alignment of the up and forward vectors
        """
        phase_bonus = reward = 0
        _, _, info = super()._compute_reward(ac)

        # clear the original success and done
        done = False
        self._success = False

        self._collect_values()
        v = self._current_values
        ctrl_penalty, ctrl_info = self._ctrl_penalty(ac)
        stable_grip_rew, sg_info = self._stable_grip_reward()
        move_other_part_penalty, move_info = self._move_other_part_penalty()

        leg_touched = v["leg_touched"]

        # detect early picking
        if leg_touched and sg_info["stable_grip_succ"] and self._phase_i < 2:
            logger.info("Skipped to lift_leg")
            # phase_bonus += self._phase_bonus * (3 - self._phase_i)
            self._phase_i = 3  # lift_leg

        # detect early fine alignment without lifting or coarse alignment
        if self._phase_i in [3, 4]:
            move_pos_dist = v["move_pos_dist"]
            move_ang_dist = v["move_ang_dist"]
            move_forward_ang_dist = v["move_forward_ang_dist"]

            if (
                move_pos_dist < self._move_pos_threshold
                and move_ang_dist > self._move_rot_threshold
                and move_forward_ang_dist > self._move_rot_threshold
            ):
                logger.info("Skipped to move_leg_fine")
                # phase_bonus += self._phase_bonus * (6 - self._phase_i)
                self._phase_i = 6  # move_leg_fine

                self._prev_move_pos_dist = move_pos_dist
                self._prev_move_ang_dist = move_ang_dist
                self._prev_move_forward_ang_dist = move_forward_ang_dist
                self._prev_proj_t = v["proj_table"]
                self._prev_proj_l = v["proj_leg"]

        # detect early alignment without lifting
        if self._phase_i == 3:
            move_above_pos_dist = v["move_above_pos_dist"]
            move_ang_dist = v["move_ang_dist"]
            move_forward_ang_dist = v["move_forward_ang_dist"]

            if (
                move_ang_dist > self._align_rot_threshold
                and move_forward_ang_dist > self._align_rot_threshold
            ):
                logger.info("Skipped to move_leg")
                # phase_bonus += self._phase_bonus * (5 - self._phase_i)
                self._phase_i = 5  # move_leg

                self._prev_move_pos_dist = move_above_pos_dist
                self._prev_move_ang_dist = move_ang_dist
                self._prev_move_forward_ang_dist = move_forward_ang_dist

        # compute phase-based reward
        phase = self._phases[self._phase_i]
        info["phase_i"] = self._phase_i + len(self._phases) * self._subtask_step
        info["subtask"] = self._subtask_step
        info["touch"] = leg_touched

        grip_penalty, grip_info = self._gripper_penalty(ac)

        if phase == "move_eef_above_leg":
            phase_reward, phase_info = self._move_eef_above_leg_reward()
            if phase_info[f"{phase}_succ"] and sg_info["stable_grip_succ"]:
                self._phase_i += 1
                phase_bonus += self._phase_bonus

                eef_pos = self._get_gripper_pos()
                leg_pos = self._get_leg_grasp_pos(self._leg) + [0, 0, -0.015]
                xy_dist = np.linalg.norm(eef_pos[:2] - leg_pos[:2])
                z_dist = np.abs(eef_pos[2] - leg_pos[2])
                self._prev_eef_leg_dist = min(xy_dist + z_dist, 0.3)

        elif phase == "lower_eef_to_leg":
            phase_reward, phase_info = self._lower_eef_to_leg_reward()
            if phase_info[f"{phase}_succ"] and sg_info["stable_grip_succ"]:
                phase_bonus += self._phase_bonus
                self._phase_i += 1

        elif phase == "grasp_leg":
            phase_reward, phase_info = self._grasp_leg_reward(ac)
            if phase_info["grasp_leg_succ"] and sg_info["stable_grip_succ"]:
                self._phase_i += 1
                phase_bonus += self._phase_bonus

        elif phase == "lift_leg":
            phase_reward, phase_info = self._lift_leg_reward()

            if not leg_touched:
                logger.info("Dropped leg during lifting")
                done = True
                phase_bonus += -self._phase_bonus / 2

            elif move_info["table_displacement"] > 0.1:
                logger.info("Moved table too much during lifting")
                done = True
                phase_bonus += -self._phase_bonus / 2

            elif phase_info["lift_leg_succ"]:
                self._phase_i += 1
                phase_bonus += self._phase_bonus

                self._align_leg_pos = self._get_pos(self._leg)
                self._prev_move_pos_dist = 0
                self._prev_move_ang_dist = v["move_ang_dist"]
                self._prev_move_forward_ang_dist = v["move_forward_ang_dist"]

        elif phase == "align_leg":
            phase_reward, phase_info = self._align_leg_reward()

            if not leg_touched:
                logger.info("Dropped leg during aligning")
                done = True
                phase_bonus += -self._phase_bonus / 2

            elif move_info["table_displacement"] > 0.1:
                logger.info("Moved table too much during move_leg")
                done = True
                phase_bonus += -self._phase_bonus / 2

            elif phase_info["align_leg_succ"]:
                self._phase_i += 1
                phase_bonus += self._phase_bonus

                self._prev_move_pos_dist = v["move_above_pos_dist"]

        elif phase == "move_leg":
            phase_reward, phase_info = self._move_leg_reward()

            if not leg_touched:
                logger.info("Dropped leg during move_leg")
                done = True
                phase_bonus += -self._phase_bonus / 2

            elif move_info["table_displacement"] > 0.1:
                logger.info("Moved table too much during move_leg")
                done = True
                phase_bonus += -self._phase_bonus / 2

            elif phase_info["move_leg_succ"]:
                self._phase_i += 1
                phase_bonus += self._phase_bonus * 5

                self._prev_move_pos_dist = v["move_pos_dist"]
                self._prev_proj_t = v["proj_table"]
                self._prev_proj_l = v["proj_leg"]

        elif phase == "move_leg_fine":
            phase_reward, phase_info = self._move_leg_fine_reward(ac)

            if move_info["table_displacement"] > 0.1:
                logger.info("Moved table too much during move_leg_fine")
                done = True
                phase_bonus += -self._phase_bonus / 2

            elif phase_info["connect_succ"]:
                phase_bonus += self._phase_bonus * 5
                # discourage staying in algined mode
                phase_bonus -= self._leg_fine_aligned * self._aligned_bonus_coef
                self._phase_i = 0
                logger.info("*** CONNECTED!")
                # update reward variables for next attachment
                done = self._success = self._set_next_subtask()

            elif not leg_touched:
                logger.info("Dropped leg during move_leg_fine")
                done = True
                phase_bonus += -self._phase_bonus * 2

        else:
            phase_reward, phase_info = 0, {}
            done = True

        reward += ctrl_penalty + phase_reward + stable_grip_rew
        reward += grip_penalty + phase_bonus + move_other_part_penalty
        info["phase_bonus"] = phase_bonus
        info = {**info, **ctrl_info, **phase_info, **sg_info, **grip_info, **move_info}
        # log phase if last frame
        if self._episode_length == self._env_config["max_episode_steps"] - 1 or done:
            info["phase"] = self._phase_i + len(self._phases) * self._subtask_step
        return reward, done, info

    def _move_eef_above_leg_reward(self) -> Tuple[float, dict]:
        """
        Moves the eef above the leg and rotates the wrist.
        Negative euclidean distance between eef xy and leg xy.

        Return negative eucl distance
        """
        eef_pos = self._get_pos("griptip_site")
        leg_pos = self._get_leg_grasp_pos(self._leg)  # + [0, 0, 0.07]
        leg_pos[2] = 0.08
        xy_dist = np.linalg.norm(eef_pos[:2] - leg_pos[:2])
        z_dist = np.abs(eef_pos[2] - leg_pos[2])
        eef_above_leg_dist = xy_dist + z_dist
        if self._diff_rew:
            offset = self._prev_eef_above_leg_dist - eef_above_leg_dist
            rew = offset * self._eef_pos_dist_coef * 10
            self._prev_eef_above_leg_dist = eef_above_leg_dist
        else:
            rew = -eef_above_leg_dist * self._eef_pos_dist_coef
        info = {
            "eef_above_leg_dist": eef_above_leg_dist,
            "eef_above_leg_rew": rew,
            "move_eef_above_leg_succ": int(xy_dist < 0.02 and z_dist < 0.02),
        }
        return rew, info

    def _lower_eef_to_leg_reward(self) -> Tuple[float, dict]:
        """
        Moves the eef over the leg and rotates the wrist.
        Negative euclidean distance between eef xy and leg xy.
        Give additional reward for contacting the leg
        Return negative eucl distance
        """
        eef_pos = self._get_gripper_pos()
        leg_pos = self._get_leg_grasp_pos(self._leg) + [0, 0, -0.015]
        xy_dist = np.linalg.norm(eef_pos[:2] - leg_pos[:2])
        z_dist = np.abs(eef_pos[2] - leg_pos[2])
        eef_leg_dist = min(xy_dist + z_dist, 0.3)
        if self._diff_rew:
            # f = lambda x: np.exp(-25 * x)
            # offset = f(eef_leg_dist) - f(self._prev_eef_leg_dist)
            offset = self._prev_eef_leg_dist - eef_leg_dist
            rew = offset * self._lower_eef_pos_dist_coef * 10
            self._prev_eef_leg_dist = eef_leg_dist
        else:
            rew = -eef_leg_dist * self._lower_eef_pos_dist_coef

        info = {"eef_leg_dist": eef_leg_dist, "eef_leg_rew": rew}
        info["lower_eef_to_leg_succ"] = int(xy_dist < 0.02 and z_dist < 0.01)
        return rew, info

    def _grasp_leg_reward(self, ac) -> Tuple[float, dict]:
        """
        Grasp the leg, making sure it is in position
        """
        # if eef in correct position, add additional grasping success
        rew, info = self._lower_eef_to_leg_reward()

        v = self._current_values
        leg_touched = v["leg_touched"]
        info["grasp_leg_succ"] = leg_touched

        touch_rew = 0
        # touch_rew = leg_touched * self._touch_coef * 10

        # closed gripper is 1, want to maximize gripper
        offset = ac[-2] - self._prev_grasp_dist
        grasp_leg_rew = offset * self._grasp_dist_coef
        self._prev_grasp_dist = ac[-2]
        info["grasp_leg_rew"] = grasp_leg_rew

        # gripper rew, 1 if closed
        # further bonus for touch
        if leg_touched and not self._leg_touched:
            touch_rew += self._touch_coef * 10
            self._leg_touched = True
        info["touch_rew"] = touch_rew
        rew += grasp_leg_rew + touch_rew

        return rew, info

    def _lift_leg_reward(self) -> Tuple[float, dict]:
        """
        Lift the leg
        """
        v = self._current_values
        leg_touched = v["leg_touched"]

        # reward for grasping
        touch_rew = leg_touched * self._touch_coef / 5
        # touch_rew = 0
        info = {"touch_rew": touch_rew}

        # reward for lifting
        leg_pos = v["leg_pos"]
        xy_dist = np.linalg.norm(self._lift_leg_pos[:2] - leg_pos[:2])
        z_dist = np.abs(self._lift_leg_pos[2] - leg_pos[2])
        if self._diff_rew:
            z_offset = self._prev_lift_leg_z_dist - z_dist
            lift_leg_rew = z_offset * self._lift_dist_coef * 10
            self._prev_lift_leg_z_dist = z_dist
            xy_offset = self._prev_lift_leg_xy_dist - xy_dist
            lift_leg_rew += xy_offset * self._lift_dist_coef * 10
            self._prev_lift_leg_xy_dist = xy_dist
        else:
            lift_leg_rew = -(z_dist + xy_dist) * self._lift_dist_coef

        # give one time reward for lifting the leg
        leg_lift = leg_pos[2] > (self._init_lift_leg_pos[2] + 0.01)
        if (leg_touched and leg_lift) and not self._leg_lift:
            logger.info("Lift leg")
            self._leg_lift = True
            lift_leg_rew += self._phase_bonus / 10

        rew = lift_leg_rew + touch_rew
        info["lift"] = int(leg_lift)
        info["lift_leg_rew"] = lift_leg_rew
        info["lift_leg_xy_dist"] = xy_dist
        info["lift_leg_z_dist"] = z_dist
        info["lift_leg_succ"] = int(xy_dist < 0.03 and z_dist < 0.01)
        info["lift_leg_pos"] = leg_pos
        info["lift_leg_target"] = self._lift_leg_pos

        return rew, info

    def _align_leg_reward(self) -> Tuple[float, dict]:
        """
        Aligns the leg
        """
        v = self._current_values
        leg_touched = v["leg_touched"]

        # touch_rew = leg_touched * self._touch_coef
        touch_rew = 0
        info = {"touch_rew": touch_rew}

        # calculate position rew
        leg_pos = self._get_pos(self._leg)
        move_pos_dist = np.linalg.norm(self._align_leg_pos - leg_pos)
        if self._diff_rew:
            offset = self._prev_move_pos_dist - move_pos_dist
            pos_rew = offset * self._align_pos_dist_coef * 10
            self._prev_move_pos_dist = move_pos_dist
        else:
            pos_rew = -move_pos_dist * self._align_pos_dist_coef
        info.update({"align_pos_dist": move_pos_dist, "align_pos_rew": pos_rew})

        # calculate angular rew
        move_ang_dist = v["move_ang_dist"]
        if self._diff_rew:
            offset = move_ang_dist - self._prev_move_ang_dist
            ang_rew = offset * self._align_rot_dist_coef * 10
            self._prev_move_ang_dist = move_ang_dist
        else:
            ang_rew = (move_ang_dist - 1) * self._align_rot_dist_coef
        info.update({"align_ang_dist": move_ang_dist, "align_ang_rew": ang_rew})

        move_forward_ang_dist = v["move_forward_ang_dist"]
        if self._diff_rew:
            offset = move_forward_ang_dist - self._prev_move_forward_ang_dist
            forward_ang_rew = offset * self._align_rot_dist_coef * 10
            self._prev_move_forward_ang_dist = move_forward_ang_dist
        else:
            forward_ang_rew = (move_forward_ang_dist - 1) * self._align_rot_dist_coef
        info["align_forward_ang_dist"] = move_forward_ang_dist
        info["align_forward_ang_rew"] = forward_ang_rew

        info["align_leg_succ"] = int(
            move_pos_dist < self._align_pos_threshold
            and move_ang_dist > self._align_rot_threshold
            and move_forward_ang_dist > self._align_rot_threshold
            and leg_touched
        )

        rew = pos_rew + ang_rew + forward_ang_rew + touch_rew
        return rew, info

    def _move_leg_reward(self) -> Tuple[float, dict]:
        """
        Coarsely move the leg site over the conn_site
        Also give reward for angular alignment
        """
        v = self._current_values
        leg_touched = v["leg_touched"]

        # touch_rew = leg_touched * self._touch_coef
        touch_rew = 0
        info = {"touch_rew": touch_rew}

        # calculate position rew
        move_pos_dist = v["move_above_pos_dist"]
        if self._diff_rew:
            offset = self._prev_move_pos_dist - move_pos_dist
            pos_rew = offset * self._move_pos_dist_coef * 10
            self._prev_move_pos_dist = move_pos_dist
        else:
            pos_rew = -move_pos_dist * self._move_pos_dist_coef
        info.update({"move_pos_dist": move_pos_dist, "move_pos_rew": pos_rew})

        # calculate angular rew
        move_ang_dist = v["move_ang_dist"]
        if self._diff_rew:
            offset = move_ang_dist - self._prev_move_ang_dist
            ang_rew = offset * self._move_rot_dist_coef * 10
            self._prev_move_ang_dist = move_ang_dist
        else:
            ang_rew = (move_ang_dist - 1) * self._move_rot_dist_coef
        info.update({"move_ang_dist": move_ang_dist, "move_ang_rew": ang_rew})

        move_forward_ang_dist = v["move_forward_ang_dist"]
        if self._diff_rew:
            offset = move_forward_ang_dist - self._prev_move_forward_ang_dist
            forward_ang_rew = offset * self._move_rot_dist_coef * 10
            self._prev_move_forward_ang_dist = move_forward_ang_dist
        else:
            forward_ang_rew = (move_forward_ang_dist - 1) * self._move_rot_dist_coef
        info["move_forward_ang_dist"] = move_forward_ang_dist
        info["move_forward_ang_rew"] = forward_ang_rew

        info["move_leg_succ"] = int(
            move_pos_dist < self._move_pos_threshold
            and move_ang_dist > self._move_rot_threshold
            and move_forward_ang_dist > self._move_rot_threshold
            and leg_touched
        )

        rew = pos_rew + ang_rew + forward_ang_rew + touch_rew

        return rew, info

    def _move_leg_fine_reward(self, ac) -> Tuple[float, dict]:
        """
        Finely move the leg site over the conn_site
        Also give reward for angular alignment
        Also check for connected pieces
        """
        # no dense reward when completed
        info = {"connect_succ": self._connected}
        if self._connected:
            return 0, info

        v = self._current_values
        leg_touched = v["leg_touched"]

        # touch_rew = leg_touched * self._touch_coef
        touch_rew = 0
        info.update({"touch_rew": touch_rew})

        # calculate position rew
        move_pos_dist = v["move_pos_dist"]
        if self._diff_rew:
            f = lambda x: np.exp(-25 * x)
            offset = f(move_pos_dist) - f(self._prev_move_pos_dist)
            # offset = self._prev_move_pos_dist - move_pos_dist
            pos_rew = offset * self._move_fine_pos_dist_coef * 10
            self._prev_move_pos_dist = move_pos_dist
        else:
            pos_rew = -move_pos_dist * self._move_fine_pos_dist_coef
        info["move_fine_pos_dist"] = move_pos_dist
        info["move_fine_pos_rew"] = pos_rew

        # calculate angular rew
        move_ang_dist = v["move_ang_dist"]
        if self._diff_rew:
            f = lambda x: np.exp(-3 * (1 - x))
            offset = f(move_ang_dist) - f(self._prev_move_ang_dist)
            # offset = move_ang_dist - self._prev_move_ang_dist
            ang_rew = offset * self._move_fine_rot_dist_coef * 10
            self._prev_move_ang_dist = move_ang_dist
        else:
            ang_rew = (move_ang_dist - 1) * self._move_fine_rot_dist_coef
        info["move_fine_ang_dist"] = move_ang_dist
        info["move_fine_ang_rew"] = ang_rew

        move_forward_ang_dist = v["move_forward_ang_dist"]
        if self._diff_rew:
            f = lambda x: np.exp(-3 * (1 - x))
            offset = f(move_forward_ang_dist) - f(self._prev_move_forward_ang_dist)
            # offset = move_forward_ang_dist - self._prev_move_forward_ang_dist
            forward_ang_rew = offset * self._move_fine_rot_dist_coef * 10
            self._prev_move_forward_ang_dist = move_forward_ang_dist
        else:
            forward_ang_rew = (
                move_forward_ang_dist - 1
            ) * self._move_fine_rot_dist_coef
        info["move_fine_forward_ang_dist"] = move_forward_ang_dist
        info["move_fine_forward_ang_rew"] = forward_ang_rew

        # proj will approach 1 if aligned correctly
        proj_t = v["proj_table"]
        proj_l = v["proj_leg"]
        if self._diff_rew:
            f = lambda x: np.exp(-3 * (1 - x))
            offset = f(proj_t) - f(self._prev_proj_t)
            proj_t_rew = offset * self._move_fine_rot_dist_coef * 5
            self._prev_proj_t = proj_t
            offset = f(proj_l) - f(self._prev_proj_l)
            proj_l_rew = offset * self._move_fine_rot_dist_coef * 5
            self._prev_proj_l = proj_l
        else:
            proj_t_rew = (proj_t - 1) * self._move_fine_rot_dist_coef / 10
            proj_l_rew = (proj_l - 1) * self._move_fine_rot_dist_coef / 10
        info.update({"proj_t_rew": proj_t_rew, "proj_t": proj_t})
        info.update({"proj_l_rew": proj_l_rew, "proj_l": proj_l})
        info["move_leg_fine_succ"] = int(
            self._is_aligned(self._leg_site, self._table_site)
        )
        rew = pos_rew + ang_rew + forward_ang_rew + touch_rew + proj_t_rew + proj_l_rew

        if info["move_leg_fine_succ"]:
            self._leg_fine_aligned += 1
            info["connect_rew"] = (ac[-1] + 1) * self._aligned_bonus_coef
            rew += info["connect_rew"]
        return rew, info

    def _stable_grip_reward(self) -> Tuple[float, dict]:
        """
        Makes sure the eef and object axes are aligned
        Prioritize wrist alignment more than vertical alignment
        Returns negative angular distance
        """
        # up vector of leg and world up vector should be aligned
        eef_up = self._get_up_vector("grip_site")
        eef_up_grasp_dist = T.cos_siml(eef_up, [0, 0, -1])
        eef_up_grasp_rew = self._eef_up_rot_dist_coef * (eef_up_grasp_dist - 1)

        grasp_vec = self._get_leg_grasp_vector(self._leg_site)
        # up vector of leg and forward vector of grip site should be parallel (close to -1 or 1)
        eef_forward = self._get_forward_vector("grip_site")
        eef_forward_grasp_dist = T.cos_siml(eef_forward, grasp_vec)
        eef_forward_grasp_rew = (
            np.abs(eef_forward_grasp_dist) - 1
        ) * self._eef_rot_dist_coef

        # impose stable_grip_rew until lifting
        rew = eef_up_grasp_rew + eef_forward_grasp_rew
        info = {
            "stable_grip_succ": int(
                eef_up_grasp_dist > 1 - self._rot_threshold
                and np.abs(eef_forward_grasp_dist) > 1 - self._rot_threshold
            )
        }
        if self._phase_i < 3:
            info["eef_up_grasp_dist"] = eef_up_grasp_dist
            info["eef_up_grasp_rew"] = eef_up_grasp_rew
            info["eef_forward_grasp_dist"] = eef_forward_grasp_dist
            info["eef_forward_grasp_rew"] = eef_forward_grasp_rew
        else:
            rew = 0
        return rew, info

    def _gripper_penalty(self, ac) -> Tuple[float, dict]:
        """
        Give penalty on status of gripper. Only give it on phases where
        gripper should close
        Returns 0 if gripper is in desired position, range is [-2, 0]
        """
        grip_open = self._phases[self._phase_i] in self._grip_open_phases
        # ac[-2] is -1 for open, 1 for closed
        rew = 0
        if not grip_open:
            rew = (
                -1 - ac[-2] if grip_open else ac[-2] - 1
            ) * self._gripper_penalty_coef
        assert rew <= 0
        info = {"gripper_penalty": rew, "gripper_action": ac[-2]}
        return rew, info

    def _ctrl_penalty(self, action) -> Tuple[float, dict]:
        rew = np.linalg.norm(action[:-2]) * -self._ctrl_penalty_coef
        info = {"ctrl_penalty": rew}
        assert rew <= 0
        return rew, info

    def _move_other_part_penalty(self) -> Tuple[float, dict]:
        """
        At any point, the robot should minimize pose displacement in non-relevant parts.
        Return negative reward
        """
        v = self._current_values
        table_displacement = v["table_displacement"]
        rew = -self._move_other_part_penalty_coef * table_displacement
        info = {
            "move_other_part_penalty": rew,
            "table_displacement": table_displacement,
        }
        return rew, info

    def _get_gripper_pos(self) -> list:
        """return 6d pos [griptip, grip] """
        return np.concatenate(
            [self._get_pos("griptip_site"), self._get_pos("grip_site")]
        )

    def _get_fingertip_pos(self) -> list:
        """return 6d pos [left grip, right grip]"""
        return np.concatenate(
            [self._get_pos("lgriptip_site"), self._get_pos("rgriptip_site")]
        )


def main():
    from config import create_parser

    parser = create_parser(env="furniture-sawyer-densereward-v0")
    parser.add_argument(
        "--run_mode", type=str, default="manual", choices=["manual", "vr", "demo"]
    )
    config, unparsed = parser.parse_known_args()
    if len(unparsed):
        logger.error("Unparsed argument is detected:\n%s", unparsed)
        return

    # create an environment and run manual control of Sawyer environment
    env = FurnitureSawyerDenseRewardEnv(config)
    if config.run_mode == "manual":
        env.run_manual(config)
    elif config.run_mode == "vr":
        env.run_vr(config)
    elif config.run_mode == "demo":
        env.run_demo_actions(config)


if __name__ == "__main__":
    main()
