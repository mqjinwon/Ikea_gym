import collections
import copy

import numpy as np
from pyquaternion import Quaternion

from ..base import RandomizationError
from ....util import Qpos
from ... import transform_utils as T


class ObjectPositionSampler:
    """Base class of object placement sampler."""

    def __init__(self):
        pass

    def setup(self, mujoco_objects, table_top_offset, table_size):
        """
        Args:
            Mujoco_objects(MujocoObject * n_obj): objects to be placed
            table_top_offset(float * 3): location of table top center
            table_size(float * 3): x,y,z-FULLsize of the table
        """
        self.mujoco_objects = mujoco_objects
        self.n_obj = len(self.mujoco_objects)
        self.table_top_offset = table_top_offset
        self.table_size = table_size

    def sample(self):
        """
        Returns:
            xpos: x,y,z position of the objects in world frame
            xquat: quaternion of the objects
        """
        raise NotImplementedError


class UniformRandomSampler(ObjectPositionSampler):
    """Places all objects within the table uniformly random."""

    def __init__(self, rng, r_xyz=None, r_rot=None, use_xml_init=True, init_qpos=None):
        """
        Args:
            r_xyz(float): override the range used to uniformly place objects
                    if None, default to range of table
            r_xyz range is with respect to (0,0) = center of table.
            r_rot:
                None: Add uniform random random z-rotation
                iterable (a,b): Uniformly randomize rotation angle between a and b (in degrees)
                value: Add fixed angle z-rotation
            use_xml_init:
                True: use xml initial positions as initial positions
                False: randomly sample initial positions from range +-self.table_size/2
        """
        self.x_range = [-r_xyz, r_xyz]
        self.y_range = [-r_xyz, r_xyz]
        if isinstance(r_rot, (int, float)):
            self.rot_range = [-r_rot, r_rot]
        else:
            self.rot_range = r_rot
        self.rng = rng
        self._use_xml_init = use_xml_init
        self.init_qpos = init_qpos

    def setup(self, mujoco_objects, table_top_offset, table_size):
        """
        Note: overrides superclass implementation.

        Args:
            Mujoco_objcts(MujocoObject * n_obj): object to be placed
            table_top_offset(float * 3): location of table top center
            table_size(float * 3): x,y,z-FULLsize of the table
        """
        self.mujoco_objects = mujoco_objects  # should be a dictionary - (name, mjcf)
        self.n_obj = len(self.mujoco_objects)
        self.table_top_offset = 0  # table_top_offset
        self.table_size = table_size
        if self.init_qpos is None:
            self.init_qpos = dict()
        remaining_objects = self.mujoco_objects.copy()
        preset_objects = []
        for obj_name, obj_mjcf in self.mujoco_objects.items():
            if obj_name not in self.init_qpos.keys():
                self.init_qpos[obj_name] = Qpos(0, 0, 0, Quaternion())
            elif self._use_xml_init:
                r = obj_mjcf.get_horizontal_radius(obj_name)
                preset_objects.append((obj_name, r, self.init_qpos[obj_name]))
                remaining_objects.pop(obj_name)
        if len(remaining_objects) > 0:
            spec_x_range, spec_y_range = self.x_range, self.y_range
            self.x_range, self.y_range = None, None
            # randomnly place remaining parts anywhere on table
            # and use that pos as starting pos for future samples
            remaining_xpos, remaining_quat = self.sample(
                objects=remaining_objects, placed_objects_orig=preset_objects
            )
            for obj_name in remaining_xpos.keys():
                xpos = remaining_xpos[obj_name]
                quat = remaining_quat[obj_name]
                self.init_qpos[obj_name] = Qpos(
                    xpos[0],
                    xpos[1],
                    xpos[2],
                    Quaternion(quat[0], quat[1], quat[2], quat[3]),
                )
            self.x_range, self.y_range = spec_x_range, spec_y_range

    def sample_x(self, obj_r):
        x_range = self.x_range
        if x_range is None:
            x_range = [-self.table_size[0] / 2, self.table_size[0] / 2]
        minimum = min(x_range)
        maximum = max(x_range)
        return self.rng.uniform(high=maximum, low=minimum)

    def sample_y(self, obj_r):
        y_range = self.y_range
        if y_range is None:
            y_range = [-self.table_size[0] / 2, self.table_size[0] / 2]
        minimum = min(y_range)
        maximum = max(y_range)
        return self.rng.uniform(high=maximum, low=minimum)

    def sample_quat(self, quaternion):
        rot_range = self.rot_range
        minimum = min(rot_range)
        maximum = max(rot_range)
        # generate noise in euler, then convert noise to quat and multiply orig quat with noise quat
        xy_noise = self.rng.uniform(high=maximum, low=maximum)
        yz_noise = 0
        xz_noise = 0
        euler_noise = [xy_noise, yz_noise, xz_noise]
        rotated_quat = T.euler_to_quat(euler_noise, quaternion)
        return rotated_quat

    def sample(self, objects=None, placed_objects_orig=None):
        pos_arr = {}
        quat_arr = {}
        index = 0
        placed_names = []
        if placed_objects_orig is None:
            placed_objects = []
        else:
            placed_objects = copy.copy(placed_objects_orig)

        if objects is None:
            objects = copy.deepcopy(self.mujoco_objects)
            for part in placed_objects:
                # don't randomly initialize parts in placed_objects
                objects.pop(part[0])
                name = part[0]
                qpos = part[2]
                pos_arr[name] = self.table_top_offset + np.array(
                    [qpos.x, qpos.y, qpos.z]
                )
                quat_arr[name] = qpos.quat

        for obj_name, obj_mjcf in objects.items():
            obj_r = obj_mjcf.get_horizontal_radius(obj_name)
            # bottom_offset = obj_mjcf.get_bottom_offset(obj_name)
            success = False
            for i in range(10000):  # 1000 retries
                obj_x = self.init_qpos[obj_name].x + self.sample_x(obj_r)
                obj_y = self.init_qpos[obj_name].y + self.sample_y(obj_r)
                obj_z = self.init_qpos[obj_name].z + 0.01  # slighly above the table
                # objects cannot overlap
                location_valid = True
                for po_name, po_r, qpos in placed_objects:
                    po_x = qpos.x
                    po_y = qpos.y
                    if np.linalg.norm([obj_x - po_x, obj_y - po_y], 2) <= po_r + obj_r:
                        location_valid = False
                        break

                if location_valid:
                    pos = self.table_top_offset + np.array([obj_x, obj_y, obj_z])
                    quat = self.sample_quat(self.init_qpos[obj_name].quat)

                    placed_objects.append(
                        (obj_name, obj_r, Qpos(pos[0], pos[1], pos[2], quat))
                    )
                    quat_arr[obj_name] = quat
                    pos_arr[obj_name] = pos
                    success = True
                    break
            if not success:
                raise RandomizationError("Cannot place all objects on the desk")
            index += 1
        return pos_arr, quat_arr
