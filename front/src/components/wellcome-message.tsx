import React from "react";
import { motion, type Variants } from "framer-motion";
import DarkLogoSvg from "../assets/dark_theme_GigaAgent_grey-ball.svg?react";
import LightLogoSvg from "../assets/light_theme_GigaAgent_black-ball.svg?react";
import { useNavigate } from "react-router-dom";
import { useTheme } from "@/components/providers/theme";

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

const MotionDarkLogo = motion.create(DarkLogoSvg);
const MotionLightLogo = motion.create(LightLogoSvg);

let hasShownWelcomeAnimation = false;

const WellcomeMessage: React.FC = () => {
  const navigate = useNavigate();
  const { isDark } = useTheme();
  const shouldAnimate = React.useMemo(() => {
    if (hasShownWelcomeAnimation) {
      return false;
    }
    hasShownWelcomeAnimation = true;
    return true;
  }, []);

  const animationState = shouldAnimate ? "hidden" : "visible";
  const LogoComponent = isDark ? MotionDarkLogo : MotionLightLogo;

  return (
    <div className="flex max-[900px]:pt-10 w-full items-center justify-center">
      <motion.div
        className="max-w-2xl text-center"
        variants={containerVariants}
        initial={animationState}
        animate="visible"
      >
        <LogoComponent
          className="mx-auto mb-2 h-16 w-[250px] sm:h-14 sm:w-[250px] md:h-7 md:w-[250px]"
          style={{ display: "block" }}
          preserveAspectRatio="xMidYMid slice"
          variants={logoVariants}
          aria-label="GigaAgent Logo"
        />
      </motion.div>
    </div>
  );
};

export default WellcomeMessage;
