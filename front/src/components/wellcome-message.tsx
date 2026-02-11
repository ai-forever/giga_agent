import React from "react";
import { motion, type Variants } from "framer-motion";
import LogoWhiteImage from "../assets/gigachain_logo.svg";
import { useNavigate } from "react-router-dom";

const curve: [number, number, number, number] = [0.19, 1, 0.22, 1];

const transitions = {
  container: {
    duration: 0.4,
    ease: curve,
    when: "beforeChildren" as const,
    staggerChildren: 0.12,
  },
  item: {
    duration: 0.55,
    ease: "easeOut" as const,
  },
  logo: {
    duration: 0.4,
    ease: curve,
  },
};

const containerVariants: Variants = {
  hidden: { opacity: 0, scale: 0.94, y: 40 },
  visible: {
    opacity: 1,
    scale: 1,
    y: 0,
    transition: transitions.container,
  },
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 18 },
  visible: {
    opacity: 1,
    y: 0,
    transition: transitions.item,
  },
};

const logoVariants: Variants = {
  hidden: { opacity: 0, scale: 0.7, rotate: -6, filter: "grayscale(10)" },
  visible: {
    opacity: 1,
    scale: 1,
    rotate: 0,
    filter: "grayscale(0)",
    transition: transitions.logo,
  },
};

const tasks = [];

let hasShownWelcomeAnimation = false;

const WellcomeMessage: React.FC = () => {
  const navigate = useNavigate();
  const shouldAnimate = React.useMemo(() => {
    if (hasShownWelcomeAnimation) {
      return false;
    }
    hasShownWelcomeAnimation = true;
    return true;
  }, []);

  const animationState = shouldAnimate ? "hidden" : "visible";

  return (
    <div className="flex min-h-[60vh] pt-30 max-[900px]:pt-10 w-full items-center justify-center">
      <motion.div
        className="max-w-2xl text-center"
        variants={containerVariants}
        initial={animationState}
        animate="visible"
      >
        <motion.img
          src={LogoWhiteImage}
          alt="GigaAgent Logo"
          className="mx-auto mb-6 h-28 w-28 sm:h-32 sm:w-32 md:h-36 md:w-36"
          variants={logoVariants}
        />
        <motion.h1
          className="text-2xl font-semibold text-gray-800 dark:text-gray-100 sm:text-3xl"
          variants={itemVariants}
        >
          Привет, я GigaAgent
        </motion.h1>
        <motion.p
          className="mt-3 text-sm text-gray-600 dark:text-gray-300 sm:text-base"
          variants={itemVariants}
        >
          Универсальный агент с открытым исходным кодом для разработчиков и
          бизнеса. <br></br>Я могу координировать, планировать и решать широкий
          спектр задач.
        </motion.p>
      </motion.div>
    </div>
  );
};

export default WellcomeMessage;
