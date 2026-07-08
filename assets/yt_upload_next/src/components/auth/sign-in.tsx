// "use client";

// import { useRouter } from "next/navigation";
// import { useState } from "react";
// import { Button } from "@/components/ui/button";
// import {
//   Card,
//   CardContent,
//   CardDescription,
//   CardFooter,
//   CardHeader,
//   CardTitle,
// } from "@/components/ui/card";
// import { Input } from "@/components/ui/input";

// export default function AuthForm() {
//   const [isSignUp, setIsSignUp] = useState(false);
//   const [email, setEmail] = useState("");
//   const [password, setPassword] = useState("");
//   const [name, setName] = useState("");
//   const [loading, setLoading] = useState(false);
//   const router = useRouter();

//   return (
//     <Card className="w-[350px] mx-auto border-white/10 bg-black/50 backdrop-blur-xl text-white">
//       <CardHeader>
//         <CardTitle>{isSignUp ? "Create Account" : "Sign In"}</CardTitle>
//         <CardDescription className="text-gray-400">
//           {isSignUp
//             ? "Enter your details to get started."
//             : "Welcome back to Socializer."}
//         </CardDescription>
//       </CardHeader>
//       <CardContent>
//         <div className="space-y-4">
//           {isSignUp && (
//             <Input
//               placeholder="Name"
//               value={name}
//               onChange={(e) => setName(e.target.value)}
//               className="bg-white/5 border-white/10 text-white placeholder:text-gray-500"
//             />
//           )}
//           <Input
//             placeholder="Email"
//             value={email}
//             onChange={(e) => setEmail(e.target.value)}
//             className="bg-white/5 border-white/10 text-white placeholder:text-gray-500"
//           />
//           <Input
//             type="password"
//             placeholder="Password"
//             value={password}
//             onChange={(e) => setPassword(e.target.value)}
//             className="bg-white/5 border-white/10 text-white placeholder:text-gray-500"
//           />
//           <Button
//             className="w-full bg-purple-600 hover:bg-purple-700 text-white border-0"
//             onClick={handleAuth}
//             disabled={loading}
//           >
//             {loading ? "Processing..." : isSignUp ? "Sign Up" : "Sign In"}
//           </Button>
//           <div className="relative">
//             <div className="absolute inset-0 flex items-center">
//               <span className="w-full border-t border-white/10" />
//             </div>
//             <div className="relative flex justify-center text-xs uppercase">
//               <span className="bg-transparent px-2 text-gray-500">
//                 Or continue with
//               </span>
//             </div>
//           </div>
//           <div className="grid grid-cols-1 gap-2">
//             <Button
//               variant="outline"
//               className="w-full bg-white/5 border-white/10 text-white hover:bg-white/10 hover:text-white"
//               onClick={() => handleSocialSignIn("google")}
//               disabled={loading}
//             >
//               Google
//             </Button>
//           </div>
//         </div>
//       </CardContent>
//       <CardFooter>
//         <Button
//           variant="link"
//           className="w-full text-gray-400 hover:text-white"
//           onClick={() => setIsSignUp(!isSignUp)}
//         >
//           {isSignUp
//             ? "Already have an account? Sign In"
//             : "Don't have an account? Sign Up"}
//         </Button>
//       </CardFooter>
//     </Card>
//   );
// }
