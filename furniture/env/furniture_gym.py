""" Gym wrapper for the IKEA Furniture Assembly Environment. """

import gym
import numpy as np

from . import make_env
from ..config.furniture import get_default_config
from ..config import create_parser


class FurnitureGym(gym.Env):
    """
    Gym wrapper class for Furniture assmebly environment.
    """

    def __init__(self, **kwarg):
        """
        Args:
            kwarg: configurations for the environment.
        """
        # config = get_default_config()

        parser = create_parser(env=kwarg["id"])
        config, _ = parser.parse_known_args()
        name = kwarg["name"]
        for key, value in kwarg.items():
            setattr(config, key, value)

        # create an environment
        self.env = make_env(name, config)

        self.observation_space = self.env.observation_space
        self.action_space = self.env.action_space

        # methods for demo
        self.run_manual = self.env.run_manual
        self.run_demo = self.env.run_demo
        self.run_vr = self.env.run_vr

        # policy sequencing methods
        self.num_subtask = self.env.num_subtask
        self.set_subtask = self.env.set_subtask
        self.set_init_qpos = self.env.set_init_qpos
        self.get_env_state = self.env.get_env_state

        self._max_episode_steps = config.max_episode_steps

    def set_max_episode_steps(self, max_episode_steps):
        self._max_episode_steps = max_episode_steps
        self.env.set_max_episode_steps(max_episode_steps)

    def reset(self):
        """
        Resets the environment.
        """
        obs = self.env.reset()
        return obs

    def step(self, action):
        """
        Computes the next environment state given @action.
        Returns observation (dict), reward (float), done (bool), and info (dict)
        """
        obs, reward, done, info = self.env.step(action)
        return obs, reward, done, info

    def render(self, mode="human"):
        """
        Renders the environment. If mode is rgb_array, we render the pixels.
        The pixels can be rgb, depth map, segmentation map
        If the mode is human, we render to the MuJoCo viewer, or for unity,
        do nothing since rendering is handled by Unity.
        """
        return self.env.render(mode)

    def close(self):
        """
        Cleans up the environment
        """
        self.env.close()


def main():
    # use gym api to make a new environment.
    env = gym.make("furniture-baxter-v0")
    # reset environment.
    env.reset()
    done = False
    while not done:
        # take a step
        ob, reward, done, info = env.step(env.action_space.sample())


if __name__ == "__main__":
    main()
